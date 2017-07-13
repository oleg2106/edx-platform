"""
Management command that will generate a blob of all grades and course metadata
as a convenient json file which is easy to subsequently serve
to external systems.
"""
import time
import calendar
import datetime
import json
import tempfile
import os

from bson import json_util

from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from django.contrib.auth.models import User

from django.test.client import RequestFactory

# Why did they have to remove course_about api?!

from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from student.models import CourseEnrollment, anonymous_id_for_user
from courseware.grades import iterate_grades_for
from openedx.core.lib.courses import course_image_url

from course_api.blocks.api import get_blocks

class Command(BaseCommand):
    can_import_settings = True
    help = """
    Generate a kursitet-style JSON data blob with grades and course metadata.
    """

    option_list = BaseCommand.option_list + (
        make_option('-m', '--meta_only',
                    action='store_true',
                    dest='meta_only',
                    default=False,
                    help='Do not collect grades, only output metadata.'),
        make_option('-e', '--exclude',
                    metavar='EXCLUDE_FILE',
                    dest='exclude_file',
                    default=False,
                    help='Name of the list of excluded courses. Optional'),
        make_option('-i', '--include',
                    metavar='INCLUDE_FILE',
                    dest='include_file',
                    default=False,
                    help='Name of the list of included courses. Optional'),
        make_option('-c', '--course',
                    metavar='SINGLE_COURSE',
                    dest='single_course',
                    default=False,
                    help='Name of a single course to dump. Optional'),
        make_option('-o', '--output',
                    metavar='FILE',
                    dest='output',
                    default=False,
                    help='Filename for grade output. JSON will be printed on stdout if this is missing.'))

    def handle(self, *args, **options):

        def get_detail(course_key, attribute):
            usage_key = course_key.make_usage_key('about', attribute)
            try:
                value = modulestore().get_item(usage_key).data
            except ItemNotFoundError:
                value = None
            return value

        def iso_date(thing):
            if isinstance(thing, datetime.datetime):
                return thing.isoformat()
            return thing

        exclusion_list = []
        inclusion_list = []

        if options['exclude_file']:
            try:
                with open(options['exclude_file'],'rb') as exclusion_file:
                    data = exclusion_file.readlines()
                exclusion_list = [x.strip() for x in data]
            except IOError:
                raise CommandError("Could not read exclusion list from '{0}'".format(options['exclude_file']))

        if options['include_file']:
            try:
                with open(options['include_file'],'rb') as inclusion_file:
                    data = inclusion_file.readlines()
                inclusion_list = [x.strip() for x in data]
            except IOError:
                raise CommandError("Could not read inclusion list from '{0}'".format(options['include_file']))

        store = modulestore()
        epoch = int(time.time())
        blob = {
            'epoch': epoch,
            'courses': [],
        }

        # For course TOC we need a user and a request. Find the first superuser defined,
        # that will be our user.
        request_user = User.objects.filter(is_superuser=True).first()
        factory = RequestFactory()

        for course in store.get_courses():

            course_id_string = course.id.to_deprecated_string()

            if options['single_course']:
                if course_id_string not in [options['single_course'].strip()]:
                    continue
            elif inclusion_list:
                if not course_id_string in inclusion_list:
                    continue
            elif exclusion_list:
                if course_id_string in exclusion_list:
                    continue

            print "Processing {}".format(course_id_string)

            students = CourseEnrollment.objects.users_enrolled_in(course.id)

            # The method of getting a table of contents for a course is quite obtuse.
            # We have to go all the way to simulating a request.

            request = factory.get('/')
            request.user = request_user

            raw_blocks = get_blocks(request, store.make_course_usage_key(course.id), request_user, 
                                requested_fields=['id', 'type', 'display_name', 'children', 'lms_web_url'])

            # We got the block structure. Now we need to massage it so we get the proper jump urls without site domain.
            # Because on the test server the site domain is wrong.
            blocks = {}
            for block_key, block in raw_blocks['blocks'].items():
                try:
                    direct_url = '/courses/' + block.get('lms_web_url').split('/courses/')[1]
                except IndexError:
                    direct_url = ''
                blocks[block_key] = {
                    'id': block.get('id', ''),
                    'display_name': block.get('display_name', ''),
                    'type': block.get('type', ''),
                    'children_ids': block.get('children', []),
                    'url': direct_url
                }

            # Then we need to recursively stitch it into a tree.
            # We're only interested in three layers of the hierarchy for now: 'course', 'chapter', 'sequential', 'vertical'.
            # Everything else is the individual blocks and problems we don't care about right now.

            INTERESTING_BLOCKS = ['course', 'chapter', 'sequential', 'vertical']

            def _get_children(parent):
                children = [blocks.get(n) for n in parent['children_ids'] if blocks.get(n)] # and blocks.get(n)['type'] in INTERESTING_BLOCKS]
                for child in children:
                    child['children'] = _get_children(child)
                parent['children'] = children
                del parent['children_ids']
                return children

            block_tree = _get_children(blocks[raw_blocks['root']])

            course_block = {
              'id': course_id_string,
              'meta_data': {
                'about': {
                    'display_name': course.display_name,
                    'media': {
                        'course_image': course_image_url(course),
                    }
                },
                'block_tree': block_tree,
                # Yes, I'm duplicating them for now, because the about section is shot.
                'display_name': course.display_name,
                'banner': course_image_url(course),
                'id_org': course.org,
                'id_number': course.number,
                'graded': course.graded,
                'hidden': course.visible_to_staff_only,
                'ispublic': not (course.visible_to_staff_only or False), # course.ispublic was removed in dogwood.
                'grading_policy': course.grading_policy,
                'advanced_modules': course.advanced_modules,
                'lowest_passing_grade': course.lowest_passing_grade,
                'start': iso_date(course.start),
                'advertised_start': iso_date(course.advertised_start),
                'end': iso_date(course.end),
                'enrollment_end': iso_date(course.enrollment_end),
                'enrollment_start': iso_date(course.enrollment_start),
                'has_started': course.has_started(),
                'has_ended': course.has_ended(),
                'overview': get_detail(course.id,'overview'),
                'short_description': get_detail(course.id,'short_description'),
                'pre_requisite_courses': get_detail(course.id,'pre_requisite_courses'),
                'video': get_detail(course.id,'video'),
              },
              'students': [x.username for x in students],
              'global_anonymous_id': { x.username:anonymous_id_for_user(x, None) for x in students },
              'local_anonymous_id': { x.username:anonymous_id_for_user(x, course.id) for x in students },
            }

            if not options['meta_only']:
                blob['grading_data_epoch'] = epoch
                course_block['grading_data'] = []
                # Grab grades for all students that have ever had anything to do with the course.
                graded_students = User.objects.filter(pk__in=CourseEnrollment.objects.filter(course_id=course.id).values_list('user',flat=True))
                print "{0} graded students in course {1}".format(graded_students.count(),course_id_string)
                if graded_students.count():
                    for student, gradeset, error_message \
                        in iterate_grades_for(course.id, graded_students):
                        if gradeset:
                            course_block['grading_data'].append({
                                'username': student.username,
                                'grades': gradeset,
                            })
                        else:
                            print error_message

            blob['courses'].append(course_block)
        if options['output']:
            # Ensure the dump is atomic.
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(options['output']), delete=False) as output_file:
                json.dump(blob, output_file, default=json_util.default)
                tempname = output_file.name
            os.rename(tempname, options['output'])
        else:
            print "Blob output:"
            print json.dumps(blob, indent=2, ensure_ascii=False, default=json_util.default)
