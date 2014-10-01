from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

import json

from student.models import UserProfile

class Command(BaseCommand):
    help = \
''' Extract user information into a JSON file for import into
Kursitet user database.
Pass a single filename.'''

    def handle(self, *args, **options):
        try:
            with open(args[0], 'w') as f:
                users = User.objects.all()
                userlist = []
                for user in users:
                    profile = UserProfile.objects.get(user=user)
                    record = {
                      'username': user.username,
                      'email': user.email,
                      'first_name': user.first_name,
                      'last_name': user.last_name,
                      'password': user.password,
                      'is_active': user.is_active,
                      'is_staff': user.is_staff,
                      'is_superuser': user.is_superuser,
                      # Just in case we are going to dump the entirety.
                      # Only name components, work_login and allowed_courses
                      # actually contain any information, though.
                      'profile': {
                         'name': profile.name,
                         'lastname': profile.lastname,
                         'firstname': profile.firstname,
                         'middlename': profile.middlename,
                         'meta': profile.meta,
                         'courseware': profile.courseware,
                         'year_of_birth': profile.year_of_birth,
                         'gender': profile.gender,
                         'language': profile.language,
                         'location': profile.location,
                         'level_of_education': profile.level_of_education,
                         'education_place': profile.education_place,
                         'education_year': profile.education_year,
                         'education_qualification': profile.education_qualification,
                         'education_specialty': profile.education_specialty,
                         'work_type': profile.work_type,
                         'work_number': profile.work_number,
                         'work_name': profile.work_name,
                         'work_login': profile.work_login,
                         'work_location': profile.work_location,
                         'work_occupation': profile.work_occupation,
                         'work_occupation_other': profile.work_occupation_other,
                         'work_teaching_experience': profile.work_teaching_experience,
                         'work_managing_experience': profile.work_managing_experience,
                         'work_qualification_category': profile.work_qualification_category,
                         'work_qualification_category_year': profile.work_qualification_category_year,
                         'contact_phone': profile.contact_phone,
                         'allowed_courses': profile.allowed_courses,
                         'mailing_address': profile.mailing_address,
                         'city': profile.city,
                         'country': profile.country,
                         'goals': profile.goals,
                         'allow_certificate': profile.allow_certificate,
                         'spammer': profile.spammer,
                      }
                    }
                    userlist.append(record)
                json.dump(userlist, f)
        except:
            raise CommandError('Filename required.')

