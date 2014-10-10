'''
django admin pages for courseware model
'''

from student.models import UserProfile, UserTestGroup, CourseEnrollmentAllowed
from student.models import CourseEnrollment, Registration, PendingNameChange
from ratelimitbackend import admin

# Mihara: Adding inline UserProfile to user.

from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    fields = (
        'name',
        'firstname',
        'lastname',
        'middlename',
        'work_login',
        'allowed_courses',
        'meta',
        'spammer',
    )

class UserWithProfileAdmin(UserAdmin):
    inlines = [UserProfileInline, ]

    list_display = (
        'id',
        'username',
        'email',
        'is_superuser',
        'is_staff',
        'is_active',
    )


#admin.site.unregister(User)
admin.site.register(User, UserWithProfileAdmin)

admin.site.register(UserProfile)

admin.site.register(UserTestGroup)

admin.site.register(CourseEnrollment)

admin.site.register(CourseEnrollmentAllowed)

admin.site.register(Registration)

admin.site.register(PendingNameChange)

