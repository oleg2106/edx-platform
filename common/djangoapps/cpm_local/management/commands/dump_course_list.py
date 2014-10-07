# coding: utf-8
'''
Urgent request for curriculum csv
'''

import json
import logging
import codecs

import unicodecsv

from django.core.management.base import BaseCommand, CommandError

from xmodule.modulestore.django import modulestore
from courseware.access import _has_staff_access_to_course_id
from django.contrib.auth.models import User

from django.core.management import call_command
from StringIO import StringIO

LOG = logging.getLogger(__name__)

class Command(BaseCommand):
    '''Base command class.'''

    option_list = BaseCommand.option_list
    args = '[file name]'
    help = 'Dump a list of courses and essential data about them to csv.'

    def handle(self, *args, **options):
        '''Handle management command request'''

        output_filename = 'curriculum.csv'

        if len(args) > 1:
            raise CommandError('Usage is dump_course_list {0}'.format(self.args))
        elif len(args) == 1:
            output_filename = args[0]

        store = modulestore('default')

        # note: course urls are like "https://edu.olimpiada.ru/courses/{0}/about".format(course_id)

        results = []
        for courserecord in store.get_courses():
            course = courserecord.location.course_id
            coursedata = {'course_id': '', 'url': '', 'course_name': '', 'students': 0}
            coursedata['course_id'] = course
            coursedata['url'] = "https://edu.olimpiada.ru/courses/{0}/about".format(course)

            content = StringIO()
            course_structure_dump = call_command('dump_course_structure',course,interactive = False,stdout=content)
            content.seek(0)
            metadata = json.loads(content.read())

            for metaitemid in metadata:
                metaitem = metadata[metaitemid]
                if 'category' in metaitem and metaitem['category']=='course' and 'metadata' in metaitem:
                    if 'ispublic' in metaitem['metadata'] and metaitem['metadata']['ispublic']:
                        coursedata['course_name'] = u"{number}: {name}".format(
                            number=metaitem['metadata']['display_coursenumber'],
                            name=metaitem['metadata']['display_name']
                        )

            enrolled_students = User.objects.filter(courseenrollment__course_id=course,).prefetch_related("groups").order_by('username')
            enrolled_students = [st for st in enrolled_students if not _has_staff_access_to_course_id(st, course)]
            coursedata['students'] = len(enrolled_students)
            results.append(coursedata)

        with open(output_filename,'w') as handle:
			writer = unicodecsv.DictWriter(handle,results[0].keys(),encoding='utf-8')
			writer.writeheader()
			for row in results:
				writer.writerow(row)


