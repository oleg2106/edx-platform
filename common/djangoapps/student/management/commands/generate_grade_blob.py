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
from student.models import CourseEnrollment
from courseware.grades import iterate_grades_for

class Command(BaseCommand):
    can_import_settings = True
    help = """
    Generate a kursitet-style JSON data blob with grades and course metadata.

    -e, --exclude -- name of a file containing a list of course IDs to exclude from the blob. Optional.
    -o, --output -- name of the output file.
    """

    option_list = BaseCommand.option_list + (
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
        
        blob = {
            'epoch': int(time.time()),
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
                course_block = {
                  'id': course_id_string,
                  'about': get_course_about_details(course_id_string),
                }
                course_block['grading_data'] = []
                students = CourseEnrollment.users_enrolled_in(course.id)
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
