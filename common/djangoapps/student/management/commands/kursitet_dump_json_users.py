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
                l = []
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
                      'profile': {
                         'name': profile.name,
                         'language': profile.language,
                         'location': profile.location,
                      }
                    }
                    l.append(record)
                json.dump(l, f)
        except:
            raise CommandError('Filename required.')

