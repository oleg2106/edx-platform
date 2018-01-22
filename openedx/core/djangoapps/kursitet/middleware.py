from django.contrib.auth.decorators import login_required


class ExtraLoginRequired(object):
    """
    When using CAS login, while attempting to make authorization completely
    seamless, it is useful to be able to make any page a user can concievably
    reach from outside login_required.  Altering all the views involved could
    become too invasive, however, so we're confining this change to a
    middleware so as to keep the intrusion to a minimum.
    """

    RESTRICT_VIEWS = [
        # LMS
        "branding.views.index",
        "branding.views.courses",
        'courseware.views.views.jump_to',
        'courseware.views.views.jump_to_id',
        'courseware.views.views.course_about',
        'courseware.views.views.course_info',
        'courseware.views.views.syllabus',
        'courseware.views.views.course_survey',
        'courseware.views.views.progress',
        'courseware.views.views.program_marketing',
        'student.views.register_user',
        'student_account.views.login_and_registration_form',

        # Studio
        "contentstore.views.public.signup",
        "contentstore.views.public.howitworks",
        "contentstore.views.howitworks",
    ]

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated() or \
           not "{0}.{1}".format(view_func.__module__, view_func.__name__) \
           in self.RESTRICT_VIEWS:
            return None
        return login_required(view_func)(request, *view_args, **view_kwargs)
