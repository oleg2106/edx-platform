# coding: utf-8
'''
Set the course end date directly. Intended to be used for bulk course expiration.
'''

import json
import logging

from django.core.management.base import BaseCommand, CommandError

from xmodule.modulestore.django import modulestore, loc_mapper
from django.contrib.auth.models import User

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
    args = '<yyyy/mm/dd> <email of a user>'
    help = 'Set all the courses in the database to expire on that date. Email is required to record who is making the change.'

    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 2:
            raise CommandError('Usage is set_course_end {0}'.format(self.args))

        try:
            end_date = pytz.timezone('Europe/Moscow').localize(parse_date(args[0],dayfirst=False,yearfirst=True))
        except:
            raise CommandError('Could not parse date "{0}"'.format(args[0]))
        try:
            user = User.objects.get(email=args[1])
        except:
            raise CommandError('Could not find user with email "{0}"'.format(args[1]))

        store = modulestore('default')

        for courserecord in store.get_courses():
            course_id = courserecord.location.course_id
            if query_yes_no("Setting end date {date} for course {id}. (currently {cur}) Proceed?".format(date=end_date,id=course_id,cur=courserecord.end),default='no'):
                # This is pure voodoo made by cobbling together poorly understood bits of tests for CMS.
                # Seems to work correctly...
                course_locator = loc_mapper().translate_location(courserecord.location.course_id,courserecord.location,False,True)
                coursedata = CourseDetails.fetch(course_locator)
                coursedata.end_date = end_date
                coursedata.update_from_json(course_locator,coursedata.__dict__,user)

