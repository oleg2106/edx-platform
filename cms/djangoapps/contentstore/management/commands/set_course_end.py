# coding: utf-8
'''
Set the course end date directly. Intended to be used for bulk course expiration.
'''

import json
import logging

from django.core.management.base import BaseCommand, CommandError

from xmodule.modulestore.django import modulestore
from django.contrib.auth.models import User

from opaque_keys.edx.locator import CourseLocator
from models.settings.course_details import (CourseDetails, CourseSettingsEncoder)
from models.settings.course_metadata import CourseMetadata

import datetime
import pytz
from dateutil.parser import parse as parse_date
from .prompt import query_yes_no

LOG = logging.getLogger(__name__)

class Command(BaseCommand):
    '''Base command class.'''

    option_list = BaseCommand.option_list
    args = '<course_id> <yyyy/mm/dd> <email of a user>'
    help = 'Set a course in the database to expire on that date. Email is required to record who is making the change.'

    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 3:
            raise CommandError('Usage is set_course_end {0}'.format(self.args))

        try:
            end_date = pytz.timezone('Europe/Moscow').localize(parse_date(args[1],dayfirst=False,yearfirst=True)).astimezone(pytz.utc)
        except:
            raise CommandError('Could not parse date "{0}"'.format(args[1]))
        try:
            user = User.objects.get(email=args[2])
        except:
            raise CommandError('Could not find user with email "{0}"'.format(args[2]))

        locator = CourseLocator.from_string(args[0])

        coursedata = CourseDetails.fetch(locator)
        old_end_date = coursedata.end_date
        coursedata.end_date = end_date
        print "Changing course {0} end date from {1} to {2}".format(locator,old_end_date,end_date)
        coursedata.update_from_json(locator,coursedata.__dict__,user)



