"""
Management command that will generate a blob of all grades and course metadata
as a convenient json file which is easy to subsequently serve
to external systems.
"""

import time
import json
import tempfile
import os
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
from xmodule.modulestore.django import modulestore

from openedx.core.djangoapps.kursitet.metadata import get_course_block


class Command(BaseCommand):
    can_import_settings = True
    help = """
    Generate a kursitet-style JSON data blob with grades and course metadata.
    """

    option_list = BaseCommand.option_list + (
        make_option(
            '-m',
            '--meta_only',
            action='store_true',
            dest='meta_only',
            default=False,
            help='Do not collect grades, only output metadata.'), make_option(
                '-e',
                '--exclude',
                metavar='EXCLUDE_FILE',
                dest='exclude_file',
                default=False,
                help='Name of the list of excluded courses. Optional'),
        make_option(
            '-i',
            '--include',
            metavar='INCLUDE_FILE',
            dest='include_file',
            default=False,
            help='Name of the list of included courses. Optional'),
        make_option(
            '-c',
            '--course',
            metavar='SINGLE_COURSE',
            dest='single_course',
            default=False,
            help='Name of a single course to dump. Optional'), make_option(
                '-o',
                '--output',
                metavar='FILE',
                dest='output',
                default=False,
                help='Filename for grade output. '
                'JSON will be printed on stdout if this is missing.'))

    def handle(self, *args, **options):

        exclusion_list = []
        inclusion_list = []

        if options['exclude_file']:
            try:
                with open(options['exclude_file'], 'rb') as exclusion_file:
                    data = exclusion_file.readlines()
                exclusion_list = [x.strip() for x in data]
            except IOError:
                raise CommandError("Could not read exclusion list from '{0}'".
                                   format(options['exclude_file']))

        if options['include_file']:
            try:
                with open(options['include_file'], 'rb') as inclusion_file:
                    data = inclusion_file.readlines()
                inclusion_list = [x.strip() for x in data]
            except IOError:
                raise CommandError("Could not read inclusion list from '{0}'".
                                   format(options['include_file']))

        store = modulestore()
        epoch = int(time.time())
        blob = {
            'epoch': epoch,
            'courses': [],
        }

        for course in store.get_courses():

            course_id_string = course.id.to_deprecated_string()

            if options['single_course']:
                if course_id_string not in [options['single_course'].strip()]:
                    continue
            elif inclusion_list:
                if course_id_string not in inclusion_list:
                    continue
            elif exclusion_list:
                if course_id_string in exclusion_list:
                    continue

            print "Processing {}".format(course_id_string)

            course_block = get_course_block(
                course, get_grades=not options['meta_only'])
            if not options['meta_only']:
                blob['grading_data_epoch'] = epoch
            blob['courses'].append(course_block)

        if options['output']:
            # Ensure the dump is atomic.
            with tempfile.NamedTemporaryFile(
                    'w', dir=os.path.dirname(options['output']),
                    delete=False) as output_file:
                json.dump(blob, output_file)
                tempname = output_file.name
            os.rename(tempname, options['output'])
        else:
            print "Blob output:"
            print json.dumps(blob, indent=2, ensure_ascii=False)
