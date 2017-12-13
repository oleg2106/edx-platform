"""
Celery tasks that actually poke the Kursitet API with our data.
"""
import logging
import requests

from django.conf import settings
from django.dispatch import receiver

from lms import CELERY_APP
from xmodule.modulestore.django import SignalHandler

from kursitet.metadata import get_course_block_by_id

log = logging.getLogger(__name__)


@receiver(SignalHandler.course_published)
def kursitet_course_published_handler(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Consume signals that indicate course published.
    Trigger an async update in Kursitet upon reception.
    """
    update_course.delay(unicode(course_key))


@CELERY_APP.task
def update_course(course_id):
    """
    Send an update packet of course metadata to Kursitet.
    """
    if not settings.KURSITET_API_ENDPOINT or not settings.KURSITET_API_TOKEN:
        log.warn("Kursitet API endpoint not configured, "
                 "not posting a course metadata update.")
        return

    # Get our course data block...
    course_data = get_course_block_by_id(course_id, get_grades=False)

    # WIP: I am not sure what to do to test that...
    # CMS sends a message over to LMS upon publishing course,
    # which is *supposed* to trigger this task.
    # Unfortunately, the entire mechanism does not appear to work in devstack.

    # For debugging, don't do anything, let's see if we get executed correctly first.
    # import json
    # log.info("Got called with course id ".format(course_id))
    #log.info("json blob:" + json.dumps(
    #    course_data, indent=2, ensure_ascii=False))
    # return

    # Prepare a request.
    headers = {'Authorization': 'Token ' + settings.KURSITET_API_TOKEN}
    try:
        r = requests.post(
            settings.KURSITET_API_ENDPOINT + '/course_update/',
            json=course_data,
            headers=headers,
            timeout=20)
    except requests.exceptions.Timeout:
        # In case of a timeout, log error
        log.error("Timeout when trying to send a course update to Kursitet.")
    if r.status_code != 200:
        # Something was wrong, so we die and log another error.
        log.error("Something went wrong when trying to send a course "
                  "update to Kursitet, error {}".format(r.status_code))
    return
