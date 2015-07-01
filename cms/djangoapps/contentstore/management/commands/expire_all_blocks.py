# coding: utf-8
'''
Mass set of block due dates for a particular course. Intended to be used for bulk course expiration.
'''

import json
import datetime
import pytz

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from dateutil.parser import parse as parse_date

from opaque_keys.edx.locator import CourseLocator
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.django import modulestore

class Command(BaseCommand):

    option_list = BaseCommand.option_list
    args = '<course_id> <yyyy/mm/dd> <email of a user>'
    help = 'Set all sequence blocks in a course in the database to be due on that date. Email is required to record who is making the change.'

    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 3:
            raise CommandError('Usage is expire_all_blocks {0}'.format(self.args))

        try:
            end_date = pytz.timezone('Europe/Moscow').localize(parse_date(args[1],dayfirst=False,yearfirst=True)).astimezone(pytz.utc)
        except:
            raise CommandError('Could not parse date "{0}"'.format(args[1]))
        try:
            user = User.objects.get(email=args[2])
        except:
            raise CommandError('Could not find user with email "{0}"'.format(args[2]))

        locator = CourseLocator.from_string(args[0])

        print "Altering course {0} blocks due date to {1}".format(locator,end_date)

        for block in modulestore().get_items(locator,qualifiers={'category':'sequential'},revision=ModuleStoreEnum.RevisionOption.published_only):
            block.due = end_date
            modulestore().update_item(block, user.id)

