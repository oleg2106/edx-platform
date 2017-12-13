"""

Common functionality used to extract the data kursitet wants.

"""

import datetime
from django.contrib.auth.models import User
from django.test.client import RequestFactory
from student.models import CourseEnrollment, anonymous_id_for_user
from lms.djangoapps.grades.new.course_grade_factory import CourseGradeFactory
from openedx.core.lib.courses import course_image_url
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from course_api.blocks.api import get_blocks


def get_student_grades(course, graded_students):
    """
    Return all the student grades for a given course.
    Expects a course object rather than a course locator.
    """

    data_block = []

    if graded_students.count():
        for student in graded_students:
            grade = CourseGradeFactory().create(student, course)
            data_block.append({
                'username': student.username,
                'grades': {
                    'grade': grade.letter_grade,
                    'percent': grade.percent,
                    'summary': grade.summary,
                }
            })
    return data_block


def get_course_block(course, get_grades=False):
    """
    Return a blob of course metadata the way kursitet likes it.
    Expects a course object rather than a course locator.

    For the record: This only works in LMS context, because in CMS context,
    there's no jump_to, and these urls can't be reversed. Which means
    that CMS needs to trigger an LMS worker to send data...
    """

    def iso_date(thing):
        if isinstance(thing, datetime.datetime):
            return thing.isoformat()
        return thing

    def get_detail(course_key, attribute):
        usage_key = course_key.make_usage_key('about', attribute)
        try:
            value = modulestore().get_item(usage_key).data
        except ItemNotFoundError:
            value = None
        return value

    course_id_string = course.id.to_deprecated_string()
    store = modulestore()

    students = CourseEnrollment.objects.users_enrolled_in(course.id)

    # For course TOC we need a user and a request. Find the first superuser defined,
    # that will be our user.
    request_user = User.objects.filter(is_superuser=True).first()
    factory = RequestFactory()

    # The method of getting a table of contents for a course is quite obtuse.
    # We have to go all the way to simulating a request.

    request = factory.get('/')
    request.user = request_user

    raw_blocks = get_blocks(
        request,
        store.make_course_usage_key(course.id),
        request_user,
        requested_fields=[
            'id', 'type', 'display_name', 'children', 'lms_web_url'
        ])

    # We got the block structure. Now we need to massage it so we get the
    # proper jump urls without the site domain.
    # Because on the test server the site domain is wrong.
    blocks = {}
    for block_key, block in raw_blocks['blocks'].items():
        try:
            direct_url = '/courses/' + \
                block.get('lms_web_url').split('/courses/')[1]
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

    def _get_children(parent):
        children = [
            blocks.get(n) for n in parent['children_ids'] if blocks.get(n)
        ]
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
            'block_tree':
            block_tree,
            # Yes, I'm duplicating them for now, because the about section is shot.
            'display_name':
            course.display_name,
            'banner':
            course_image_url(course),
            'id_org':
            course.org,
            'id_number':
            course.number,
            'graded':
            course.graded,
            'hidden':
            course.visible_to_staff_only,
            # course.ispublic was removed in dogwood.
            'ispublic':
            not (course.visible_to_staff_only or False),
            'grading_policy':
            course.grading_policy,
            'advanced_modules':
            course.advanced_modules,
            'lowest_passing_grade':
            course.lowest_passing_grade,
            'start':
            iso_date(course.start),
            'advertised_start':
            iso_date(course.advertised_start),
            'end':
            iso_date(course.end),
            'enrollment_end':
            iso_date(course.enrollment_end),
            'enrollment_start':
            iso_date(course.enrollment_start),
            'has_started':
            course.has_started(),
            'has_ended':
            course.has_ended(),
            'overview':
            get_detail(course.id, 'overview'),
            'short_description':
            get_detail(course.id, 'short_description'),
            'pre_requisite_courses':
            get_detail(course.id, 'pre_requisite_courses'),
            'video':
            get_detail(course.id, 'video'),
        },
        'students': [x.username for x in students],
        'global_anonymous_id':
        {x.username: anonymous_id_for_user(x, None)
         for x in students},
        'local_anonymous_id':
        {x.username: anonymous_id_for_user(x, course.id)
         for x in students},
    }

    if get_grades:
        course_block['grading_data'] = get_student_grades(course, students)

    return course_block
