"""
A models.py is required to make this an app.
We aren't actually going to do anything to the database here, though.

"""

from django.dispatch import receiver
from xmodule.modulestore.django import modulestore, SignalHandler
from openedx.core.djangoapps.kursitet.tasks import \
    send_kursitet_course_update, send_kursitet_grade_update
from lms.djangoapps.grades.signals.signals import PROBLEM_WEIGHTED_SCORE_CHANGED


@receiver(PROBLEM_WEIGHTED_SCORE_CHANGED)
def kursitet_student_graded_handler(sender, **kwargs):
    """
    Consume signals that tell us when a user receives a grade.
    Trigger an async update in Kursiter upon reception.

    This should only get executed in LMS context...
    """
    send_kursitet_grade_update.delay(
        kwargs.get('user_id'), kwargs.get('course_id'))


@receiver(SignalHandler.course_published)
def kursitet_course_published_handler(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Consume signals that indicate course published.
    Trigger an async update in Kursitet upon reception.

    This gets executed in CMS context.
    """
    send_kursitet_course_update.delay(unicode(course_key))
