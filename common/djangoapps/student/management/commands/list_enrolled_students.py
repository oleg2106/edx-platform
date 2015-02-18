#!/usr/bin/python

from django.contrib.auth.models import User
from courseware.courses import get_course_by_id
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "dump list of student usernames for a course to stdout."
    
    def handle(self, *args, **options):
    
        course_id = args[0]
    
        try:
            course_key = CourseKey.from_string(course_id)
        except InvalidKeyError:
            course_key = SlashSeparatedCourseKey.from_deprecated_string(course_id)
            
        try:
            course = get_course_by_id(course_key)
        except Exception as err:  # pylint: disable=broad-except
            print "Course not found."
            return
            
        enrolled_students = User.objects.filter(
            courseenrollment__course_id=course_key,
            courseenrollment__is_active=1,
        ).values_list('username', flat=True)
        
        for student in enrolled_students:
            print student
            
        
    
