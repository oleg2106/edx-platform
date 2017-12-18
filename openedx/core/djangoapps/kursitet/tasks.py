"""
Celery tasks that actually poke the Kursitet API with our data.
"""
import logging
import requests
from celery.task import task

from django.contrib.auth.models import User
from django.conf import settings
from opaque_keys.edx.locator import CourseLocator
from openedx.core.djangoapps.kursitet.metadata import \
    get_course_block_by_id, get_student_grades, get_course_by_id

log = logging.getLogger(__name__)


@task(
    bind=True,
    max_retries=5,
    default_retry_delay=10,
    # This way the task is initiated by CMS, but gets executed in LMS context.
    # This is the key to the whole damn thing.
    routing_key='edx.lms.core.default')
def send_kursitet_course_update(self, course_id):
    """
    Send an update packet of course metadata to Kursitet.
    """
    if not settings.KURSITET_API_ENDPOINT or not settings.KURSITET_API_TOKEN:
        log.warn("Kursitet API endpoint not configured, "
                 "not posting a course metadata update.")
        return

    locator = CourseLocator.from_string(course_id)

    # Get our course data block...
    course_data = get_course_block_by_id(locator, get_grades=False)

    log.info("Sending kursitet course update for course {}".format(
        unicode(locator)))

    # Prepare a request.
    headers = {'Authorization': 'Token ' + settings.KURSITET_API_TOKEN}
    try:

        r = requests.post(
            settings.KURSITET_API_ENDPOINT + '/course_update/',
            json=course_data,
            headers=headers,
            timeout=20)

        if r.status_code != 200:
            # Something was wrong, so we die and log an error.
            log.error("Something went wrong when trying to send a course "
                      "update to Kursitet, error {}".format(r.status_code))
    except requests.exceptions.ConnectionError:
        log.error("Kursitet is unreachable!")
    except requests.exceptions.Timeout:
        # In case of a timeout, log error
        log.error("Timeout when trying to send a course update "
                  "to Kursitet, will retry.")
        self.retry()
    return


@task(
    bind=True,
    max_retries=5,
    default_retry_delay=10,
    routing_key='edx.lms.core.default')
def send_kursitet_grade_update(self, user_id, course_id):
    """
    Send an update packet of grade data to Kursitet.
    """
    if not settings.KURSITET_API_ENDPOINT or not settings.KURSITET_API_TOKEN:
        log.warn("Kursitet API endpoint not configured, "
                 "not posting a grade update.")
        return

    if not user_id or not course_id:
        log.error("Somehow, I got bogus data.")
        return

    course = get_course_by_id(CourseLocator.from_string(course_id))
    users = User.objects.filter(pk=user_id)
    if not users.exists():
        log.error("What do you mean the user who got graded does not exist?")
        return

    grade_data = get_student_grades(course, users)[0]

    username = grade_data['username']

    grade_data = {
        "course": course_id,
        "username": username,
        "grade": grade_data['grades']
    }

    log.info("Sending kursitet grade update for user {} in course {}".format(
        users[0].username, course_id))

    # Prepare a request.
    headers = {'Authorization': 'Token ' + settings.KURSITET_API_TOKEN}
    try:

        r = requests.post(
            settings.KURSITET_API_ENDPOINT + '/grade_update/',
            json=grade_data,
            headers=headers,
            timeout=20)

        if r.status_code != 200:
            # Something was wrong, so we die and log an error.
            log.error("Something went wrong when trying to send a grade "
                      "update to Kursitet, error {}".format(r.status_code))
    except requests.exceptions.ConnectionError:
        log.error("Kursitet is unreachable!")
    except requests.exceptions.Timeout:
        # In case of a timeout, log error
        log.error("Timeout when trying to send a grade update "
                  "to Kursitet, will retry.")
        self.retry()
    return
