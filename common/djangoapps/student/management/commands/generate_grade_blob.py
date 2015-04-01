"""
Management command that will generate a blob of all grades and course metadata
as a convenient json file which is easy to subsequently serve
to external systems.
"""
import time
import json
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from xmodule.modulestore.django import modulestore
from course_about.api import get_course_about_details
from student.models import CourseEnrollment, CourseAccessRole
from courseware.grades import iterate_grades_for
from django_comment_common.models import Role, FORUM_ROLE_ADMINISTRATOR, \
                                         FORUM_ROLE_MODERATOR, FORUM_ROLE_COMMUNITY_TA

# Note: They don't want me to use it.
from course_about.data import _fetch_course_detail as get_detail

IMPORTANT_ROLES = {
    "administrator": FORUM_ROLE_ADMINISTRATOR,
    "moderator": FORUM_ROLE_MODERATOR,
    "assistant": FORUM_ROLE_COMMUNITY_TA,
    }

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
        make_option('-o', '--output',
                    metavar='FILE',
                    dest='output',
                    default=False,
                    help='Filename for grade output. JSON will be printed on stdout if this is missing.'))

    def handle(self, *args, **options):
    
        exclusion_list = []
        
        if options['exclude_file']:
            try:
                with open(options['exclude_file'],'rb') as exclusion_file:
                    data = exclusion_file.readlines()
                exclusion_list = [x.strip() for x in data]
            except IOError:
                raise CommandError("Could not read exclusion list from '{0}'".format(options['exclude_file']))
                
        store = modulestore()
        epoch = int(time.time())
        blob = {
            'epoch': epoch,
            'courses': [],
        }
        
        # Mihara: Notice how functions mix course.id objects and course id strings left and right...
        for course in store.get_courses():
        
            course_id_string = course.id.to_deprecated_string()
            
            if course_id_string in exclusion_list:
                print "Skipping {0} by exclusion list."
                continue
            else:
                print "Processing {0}".format(course_id_string)
                forum_roles = {}
                for packet_name, role_name in IMPORTANT_ROLES.iteritems():
                    try:
                        forum_roles[packet_name] = [x.username for x in Role.objects.get(course_id=course.id, name=role_name).users.all()]
                    except Role.DoesNotExist:
                        pass

                students = CourseEnrollment.users_enrolled_in(course.id)

                course_block = {
                  'id': course_id_string,
                  'meta_data': {
                    'about': get_course_about_details(course_id_string),
                    'ispublic': course.ispublic,
                    'lowest_passing_grade': course.lowest_passing_grade,
                    'has_started': course.has_started(),
                    'has_ended': course.has_ended(),
                    # Note: API currently does not return those natively.
                    'overview': get_detail(course.id,'overview'),
                    'short_description': get_detail(course.id,'short_description'),
                    'pre_requisite_courses': get_detail(course.id,'pre_requisite_courses'),
                    'video': get_detail(course.id,'video'),
                  },
                  'staff_data': {
                    'instructors': [x.user.username for x in CourseAccessRole.objects.filter(course_id=course.id, role='instructor')],
                    'staff': [x.user.username for x in CourseAccessRole.objects.filter(course_id=course.id, role='staff')],
                    'forum': forum_roles,
                  },
                  'students': [x.username for x in students],
                }
                
                if not options['meta_only']:
                    blob['grading_data_epoch'] = epoch
                    course_block['grading_data'] = []
                    print "{0} students in course {1}".format(students.count(),course_id_string)
                    if students.count():
                        for student, gradeset, error_message \
                            in iterate_grades_for(course.id, students):
                            if gradeset:
                                course_block['grading_data'].append({
                                    'username': student.username,
                                    'grades': gradeset,
                                })
                            else:
                                print error_message
                    
                blob['courses'].append(course_block)
        if options['output']:
            with open(options['output'],'wb') as output_file:
                json.dump(blob, output_file)
        else:
            print "Blob output:"
            print json.dumps(blob, indent=2, ensure_ascii=False)
