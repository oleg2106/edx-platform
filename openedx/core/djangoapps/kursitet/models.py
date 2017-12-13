"""
A models.py is required to make this an app.
We aren't actually going to do anything to the database here, though.

"""

from django.dispatch import receiver
from xmodule.modulestore.django import modulestore, SignalHandler
from openedx.core.djangoapps.kursitet.tasks import send_kursitet_course_update


@receiver(SignalHandler.course_published)
def kursitet_course_published_handler(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Consume signals that indicate course published.
    Trigger an async update in Kursitet upon reception.
    """
    send_kursitet_course_update.delay(unicode(course_key))
