# -*- coding: utf-8 -*-
"""
Courseware views functions
"""

import logging
import urllib

from collections import defaultdict
from django.utils.translation import ugettext as _

from django.conf import settings
from django.core.context_processors import csrf
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from edxmako.shortcuts import render_to_response, render_to_string
from django_future.csrf import ensure_csrf_cookie
from django.views.decorators.cache import cache_control
from django.db import transaction
from markupsafe import escape

from courseware import grades
from courseware.access import has_access
from courseware.courses import get_course, get_courses, get_course_with_access, get_studio_url, sort_by_announcement

from courseware.masquerade import setup_masquerade
from courseware.model_data import FieldDataCache
from .module_render import toc_for_course, get_module_for_descriptor, get_module
from courseware.models import StudentModule, StudentModuleHistory
from course_modes.models import CourseMode

from open_ended_grading import open_ended_notifications
from student.models import UserTestGroup, CourseEnrollment, user_by_anonymous_id
from student.views import course_from_id, single_course_reverification_info
from util.cache import cache, cache_if_anonymous
from util.json_request import JsonResponse
from xblock.fragment import Fragment
from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import InvalidLocationError, ItemNotFoundError, NoPathToItem
from xmodule.modulestore.search import path_to_location
from xmodule.course_module import CourseDescriptor
from xmodule.tabs import CourseTabList, StaffGradingTab, PeerGradingTab, OpenEndedGradingTab
import shoppingcart

#new
import csv, codecs, cStringIO
import datetime
from django.core.servers.basehttp import FileWrapper
import logging
from django.db import connections
from util.date_utils import strftime_localized
from student.roles import CourseTeacherRole

from microsite_configuration import microsite

log = logging.getLogger("edx.courseware")

template_imports = {'urllib': urllib}


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")

class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self

class UnicodeWriter:
    """
    A CSV writer which will write rows to CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        # Redirect output to a queue
        self.queue = cStringIO.StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, **kwds)
        self.stream = f
        self.encoder = codecs.getincrementalencoder(encoding)()

    def writerow(self, row):
        self.writer.writerow([s.encode("utf-8") for s in row])
        # Fetch UTF-8 output from the queue ...
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        # ... and reencode it into the target encoding
        data = self.encoder.encode(data)
        # write to the target stream
        self.stream.write(data)
        # empty queue
        self.queue.truncate(0)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

def stat(request):
    #user.profile.name

    if not request.user.is_staff:
            raise Http404

    context = {}
    context['courses'] = get_courses(request.user)
    context['eval_selected_course'] = request.POST.get('eval_selected_course')
    context['disc_selected_course'] = request.POST.get('disc_selected_course')
    context['eval_selected_course'] = ""

    context['csrf'] = csrf(request)['csrf_token']
    filename = '/edx/app/edxapp/edx-platform/fullstat.csv'

    if request.method == 'POST':
        if 'download_stat_unfiltered' in request.POST:
            return return_fullstat_csv('/edx/app/edxapp/edx-platform/fullstat.xls')
        elif 'download_stat_filtered' in request.POST:
            context['value_error_in_input'] = True
            try:
                register_date_min = None
                register_date_max = None
                if request.POST.get('min_date') != '':
                    register_date_min = datetime.datetime.strptime(request.POST.get('min_date'), "%d/%m/%Y")
                if request.POST.get('max_date') != '':
                    register_date_max = datetime.datetime.strptime(request.POST.get('max_date'), "%d/%m/%Y")
                context['value_error_in_input'] = False
                return return_filtered_stat_csv(\
                    school_login=request.POST.get('school_login'),\
                    register_date_min=register_date_min,\
                    register_date_max=register_date_max,\
                    account_activated=request.POST.get('activated'),\
                    complete70=request.POST.get('complete70'),\
                    complete100=request.POST.get('complete100')\
                )
            except:
                log.exception('Failed to filter')
                return render_to_response('stat.html', context)

        elif 'download_eval_stat_filtered' in request.POST:

            context['eval_value_error_in_input'] = True
            try:
                eval_date_min = None
                eval_date_max = None

                if request.POST.get('eval_min_date') != '':
                    eval_date_min = datetime.datetime.strptime(request.POST.get('eval_min_date'), "%d/%m/%Y")
                if request.POST.get('eval_max_date') != '':
                    eval_date_max = datetime.datetime.strptime(request.POST.get('eval_max_date'), "%d/%m/%Y")
                context['eval_selected_course'] = request.POST.get('eval_selected_course')
                context['eval_value_error_in_input'] = False
                return return_filtered_eval_stat_csv(\
                    #context,\
                    eval_date_min=eval_date_min,\
                    eval_date_max=eval_date_max,\
                    course=request.POST.get('eval_selected_course')
                )
            except:
                return render_to_response('stat.html', context)

        elif 'download_disc_stat_filtered' in request.POST:

            context['disc_value_error_in_input'] = True
            try:
                disc_date_min = None
                disc_date_max = None
                if request.POST.get('disc_min_date') != '':
                    disc_date_min = datetime.datetime.strptime(request.POST.get('disc_min_date'), "%d/%m/%Y")
                if request.POST.get('disc_max_date') != '':
                    disc_date_max = datetime.datetime.strptime(request.POST.get('disc_max_date'), "%d/%m/%Y")
                context['disc_value_error_in_input'] = False
                return return_filtered_disc_stat_csv(\
                    disc_date_min=disc_date_min,\
                    disc_date_max=disc_date_max,\
                )
            except:
                return render_to_response('stat.html', context)

    return render_to_response('stat.html', context)



def return_filtered_eval_stat_csv(eval_date_min, eval_date_max, course):
    """
    Will return filtered csv file with info on teacher's work on assessments.
    """

    query_template = "\
        SELECT\
            g.grader_id as name,\
            g.date_created as date_created,\
            count(g.id) as count\
        FROM \
            ora.controller_grader as g JOIN ora.controller_submission as s ON g.submission_id = s.id\
        WHERE \
            g.grader_type= 'IN' \
                AND \
            g.status_code = 'S' \
                AND\
            g.date_created >= '{}'\
                AND\
            g.date_created <= '{}'\
                {}\
        GROUP BY \
            g.grader_id,\
            YEAR(g.date_created),\
            MONTH(g.date_created)\
        ;";
    
    date_min = datetime.datetime.now() - datetime.timedelta(days=365)
    date_max = datetime.datetime.now()

    if eval_date_min is not None:
        date_min = eval_date_min

    if eval_date_max is not None:
        date_max = eval_date_max

    '''
    If eval_date_min = None and eval_date_max < now - 1year, the query will return an empty set.
    (Which is somehow logic: in this case date_min > date_max)
    '''

    course_condition = ""
    if course != '':
        course_condition = "AND s.course_id = '{0}'".format(course)

    query = query_template.format(\
        datetime.datetime.strftime(date_min, "%Y%m%d"),\
        datetime.datetime.strftime(date_max, "%Y%m%d"),\
        course_condition
        )

    wrapper = FileWrapper(file('/edx/app/edxapp/edx-platform/test.csv'))
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=test.csv'
    writer = csv.writer(response)
    encoding = 'cp1251'

    title_row = [u'Статистика по проверке работ преподавателями для курса: ']
    if course != '':
        title_row.append(course)
    else:
        title_row.append(u'все курсы')
    writer.writerow([unicode(s).encode(encoding) for s in title_row])

    start_month = date_min.month
    end_months = (date_max.year - date_min.year)*12 + date_max.month + 1
    dates = [datetime.datetime(year=yr, month=mn, day=1) for (yr, mn) in (
          ((m - 1) / 12 + date_min.year, (m - 1) % 12 + 1) for m in range(start_month, end_months)
    )]

    header_row = [u'ФИО', 'E-mail']
    for date in dates:
        header_row.append(strftime_localized(date, "%b %Y")) 
    writer.writerow([unicode(s).encode(encoding) for s in header_row])

    cursor = connections['ora'].cursor()
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()

    current_user_id = ""
    row_to_csv = [0 for x in range(len(dates)+2)]

    for row in rows:
        if current_user_id != row[0]:
            if row_to_csv[0] != 0:
                writer.writerow([unicode(s).encode(encoding) for s in row_to_csv])
            row_to_csv = [0 for x in range(len(dates)+2)]
            current_user_id = row[0]
            row_to_csv[0] = user_by_anonymous_id(current_user_id).profile.name
            row_to_csv[1] = user_by_anonymous_id(current_user_id).email
        
        for i, date in enumerate(dates):
            if date.month == row[1].month and date.year == row[1].year:
                row_to_csv[i+2] = row[2]
            else:
                pass
    
    if len(rows) > 0:
        writer.writerow([unicode(s).encode(encoding) for s in row_to_csv])
 
    return response



def return_fullstat_csv(filename):
    """
    Returns fullstat.csv file.
    """
    wrapper = FileWrapper(file(filename))
    response = HttpResponse(wrapper, content_type='text/xls')
    response['Content-Disposition'] = 'attachment; filename=fullstat.xls'
    return response


def return_filtered_stat_csv(school_login='', register_date_min=None, register_date_max=None, account_activated=None, complete70=None, complete100=None):
    """
    Returns file with data from fullstat.csv filtered according to the parameters given (indices of columns can be changed):
    [6] - school_login
    [13] - register_date_min & register_date_max (changed)
    [09] - account_activated
    [14] - complete70
    [15] - complete100

    If no values are chosen, returns a filtered file with all row of fullstat.csv which contain a valid registration date in the corresponding field.
    """

    response = HttpResponse(content_type='text/xls')
    response['Content-Disposition'] = 'attachment; filename="stat_filtered.xls"'
    writer = csv.writer(response, dialect="excel-tab")
    encoding = 'cp1251'

    with open("/edx/app/edxapp/edx-platform/fullstat.csv", "r") as fullstatfile:
        header_row = True
        first_rows = True
        for row in UnicodeReader(fullstatfile):
            if header_row:
                encoded_row = [unicode(s).encode(encoding) for s in row]
                writer.writerow(encoded_row)
                header_row = False
            elif first_rows:
                if len(row)>0 and row[0]=='-':
                    encoded_row = [unicode(s).encode(encoding) for s in row]
                    writer.writerow(encoded_row)
                else:
                    first_rows = False
            else:
                if len(row) >= 16:    # must contain at least 16 columns    # change if new columns are added
                    
                    # no text in a text input --> str type
                    # no choice in radio input --> NoneType

                    try:
                        register_date = datetime.datetime.strptime(row[13], "%d/%m/%Y")
                        if (school_login == '' or row[6] == school_login) and\
                        (register_date_min == None or register_date_min <= register_date) and\
                        (register_date_max == None or register_date <= register_date_max) and\
                        (account_activated == None or (len(row[9]) == 2) == bool(account_activated)) and\
                        (complete70 == None or (len(row[14]) == 2) == bool(complete70)) and\
                        (complete100 == None or (len(row[15]) == 2) == bool(complete100)):    # ultimate hack: len('da') == 4
                            encoded_row = [unicode(s).encode(encoding) for s in row]
                            writer.writerow(encoded_row)
                    except:
                        pass
                                        
    return response



@login_required
def view_cert(request, course_id):
    course = get_course(course_id)
    filename = "/edx/app/edxapp/cert/" + course.display_number_with_default.replace(" ", "_") + "_" + course.display_name_with_default.replace(" ", "_") + "/" + request.user.email + ".pdf"
    wrapper = FileWrapper(file(filename))
    response = HttpResponse(wrapper, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="course_cert.pdf"'

    return response


def user_groups(user):
    """
    TODO (vshnayder): This is not used. When we have a new plan for groups, adjust appropriately.
    """
    if not user.is_authenticated():
        return []

    # TODO: Rewrite in Django
    key = 'user_group_names_{user.id}'.format(user=user)
    cache_expiration = 60 * 60  # one hour

    # Kill caching on dev machines -- we switch groups a lot
    group_names = cache.get(key)
    if settings.DEBUG:
        group_names = None

    if group_names is None:
        group_names = [u.name for u in UserTestGroup.objects.filter(users=user)]
        cache.set(key, group_names, cache_expiration)

    return group_names


@ensure_csrf_cookie
@cache_if_anonymous
def courses(request):
    """
    Render "find courses" page.  The course selection work is done in courseware.courses.
    """
    courses = get_courses(request.user, request.META.get('HTTP_HOST'))
    courses = sort_by_announcement(courses)

    return render_to_response("courseware/courses.html", {'courses': courses})


def render_accordion(request, course, chapter, section, field_data_cache):
    """
    Draws navigation bar. Takes current position in accordion as
    parameter.

    If chapter and section are '' or None, renders a default accordion.

    course, chapter, and section are the url_names.

    Returns the html string
    """

    # grab the table of contents
    user = User.objects.prefetch_related("groups").get(id=request.user.id)
    request.user = user	 # keep just one instance of User
    toc = toc_for_course(user, request, course, chapter, section, field_data_cache)

    context = dict([
        ('toc', toc),
        ('course_id', course.id),
        ('csrf', csrf(request)['csrf_token']),
        ('due_date_display_format', course.due_date_display_format)
    ] + template_imports.items())
    return render_to_string('courseware/accordion.html', context)


def get_current_child(xmodule):
    """
    Get the xmodule.position's display item of an xmodule that has a position and
    children.  If xmodule has no position or is out of bounds, return the first child.
    Returns None only if there are no children at all.
    """
    if not hasattr(xmodule, 'position'):
        return None

    if xmodule.position is None:
        pos = 0
    else:
        # position is 1-indexed.
        pos = xmodule.position - 1

    children = xmodule.get_display_items()
    if 0 <= pos < len(children):
        child = children[pos]
    elif len(children) > 0:
        # Something is wrong.  Default to first child
        child = children[0]
    else:
        child = None
    return child


def redirect_to_course_position(course_module):
    """
    Return a redirect to the user's current place in the course.

    If this is the user's first time, redirects to COURSE/CHAPTER/SECTION.
    If this isn't the users's first time, redirects to COURSE/CHAPTER,
    and the view will find the current section and display a message
    about reusing the stored position.

    If there is no current position in the course or chapter, then selects
    the first child.

    """
    urlargs = {'course_id': course_module.id}
    chapter = get_current_child(course_module)
    if chapter is None:
        # oops.  Something bad has happened.
        raise Http404("No chapter found when loading current position in course")

    urlargs['chapter'] = chapter.url_name
    if course_module.position is not None:
        return redirect(reverse('courseware_chapter', kwargs=urlargs))

    # Relying on default of returning first child
    section = get_current_child(chapter)
    if section is None:
        raise Http404("No section found when loading current position in course")

    urlargs['section'] = section.url_name
    return redirect(reverse('courseware_section', kwargs=urlargs))


def save_child_position(seq_module, child_name):
    """
    child_name: url_name of the child
    """
    for position, c in enumerate(seq_module.get_display_items(), start=1):
        if c.url_name == child_name:
            # Only save if position changed
            if position != seq_module.position:
                seq_module.position = position
    # Save this new position to the underlying KeyValueStore
    seq_module.save()


def chat_settings(course, user):
    """
    Returns a dict containing the settings required to connect to a
    Jabber chat server and room.
    """
    domain = getattr(settings, "JABBER_DOMAIN", None)
    if domain is None:
        log.warning('You must set JABBER_DOMAIN in the settings to '
                    'enable the chat widget')
        return None

    return {
        'domain': domain,

        # Jabber doesn't like slashes, so replace with dashes
        'room': "{ID}_class".format(ID=course.id.replace('/', '-')),

        'username': "{USER}@{DOMAIN}".format(
            USER=user.username, DOMAIN=domain
        ),

        # TODO: clearly this needs to be something other than the username
        #       should also be something that's not necessarily tied to a
        #       particular course
        'password': "{USER}@{DOMAIN}".format(
            USER=user.username, DOMAIN=domain
        ),
    }


@login_required
@ensure_csrf_cookie
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def index(request, course_id, chapter=None, section=None,
          position=None):
    """
    Displays courseware accordion and associated content.  If course, chapter,
    and section are all specified, renders the page, or returns an error if they
    are invalid.

    If section is not specified, displays the accordion opened to the right chapter.

    If neither chapter or section are specified, redirects to user's most recent
    chapter, or the first chapter if this is the user's first visit.

    Arguments:

     - request    : HTTP request
     - course_id  : course id (str: ORG/course/URL_NAME)
     - chapter    : chapter url_name (str)
     - section    : section url_name (str)
     - position   : position in module, eg of <sequential> module (str)

    Returns:

     - HTTPresponse
    """
    user = User.objects.prefetch_related("groups").get(id=request.user.id)
    request.user = user  # keep just one instance of User
    course = get_course_with_access(user, course_id, 'load', depth=2)
    staff_access = has_access(user, course, 'staff')
    registered = registered_for_course(course, user)
    if not registered:
        # TODO (vshnayder): do course instructors need to be registered to see course?
        log.debug(u'User %s tried to view course %s but is not enrolled', user, course.location.url())
        return redirect(reverse('about_course', args=[course.id]))

    masq = setup_masquerade(request, staff_access)

    try:
        field_data_cache = FieldDataCache.cache_for_descriptor_descendents(
            course.id, user, course, depth=2)

        course_module = get_module_for_descriptor(user, request, course, field_data_cache, course.id)
        if course_module is None:
            log.warning(u'If you see this, something went wrong: if we got this'
                        u' far, should have gotten a course module for this user')
            return redirect(reverse('about_course', args=[course.id]))

        studio_url = get_studio_url(course_id, 'course')

        if chapter is None:
            return redirect_to_course_position(course_module)

        context = {
            'csrf': csrf(request)['csrf_token'],
            'accordion': render_accordion(request, course, chapter, section, field_data_cache),
            'COURSE_TITLE': course.display_name_with_default,
            'course': course,
            'init': '',
            'fragment': Fragment(),
            'staff_access': staff_access,
            'studio_url': studio_url,
            'masquerade': masq,
            'xqa_server': settings.FEATURES.get('USE_XQA_SERVER', 'http://xqa:server@content-qa.mitx.mit.edu/xqa'),
            'reverifications': fetch_reverify_banner_info(request, course_id),
        }

        # Only show the chat if it's enabled by the course and in the
        # settings.
        show_chat = course.show_chat and settings.FEATURES['ENABLE_CHAT']
        if show_chat:
            context['chat'] = chat_settings(course, user)
            # If we couldn't load the chat settings, then don't show
            # the widget in the courseware.
            if context['chat'] is None:
                show_chat = False

        context['show_chat'] = show_chat

        chapter_descriptor = course.get_child_by(lambda m: m.url_name == chapter)
        if chapter_descriptor is not None:
            save_child_position(course_module, chapter)
        else:
            raise Http404('No chapter descriptor found with name {}'.format(chapter))

        chapter_module = course_module.get_child_by(lambda m: m.url_name == chapter)
        if chapter_module is None:
            # User may be trying to access a chapter that isn't live yet
            if masq == 'student':  # if staff is masquerading as student be kinder, don't 404
                log.debug('staff masq as student: no chapter %s' % chapter)
                return redirect(reverse('courseware', args=[course.id]))
            raise Http404

        if section is not None:
            section_descriptor = chapter_descriptor.get_child_by(lambda m: m.url_name == section)
            if section_descriptor is None:
                # Specifically asked-for section doesn't exist
                if masq == 'student':  # if staff is masquerading as student be kinder, don't 404
                    log.debug('staff masq as student: no section %s' % section)
                    return redirect(reverse('courseware', args=[course.id]))
                raise Http404

            # cdodge: this looks silly, but let's refetch the section_descriptor with depth=None
            # which will prefetch the children more efficiently than doing a recursive load
            section_descriptor = modulestore().get_instance(course.id, section_descriptor.location, depth=None)

            # Load all descendants of the section, because we're going to display its
            # html, which in general will need all of its children
            section_field_data_cache = FieldDataCache.cache_for_descriptor_descendents(
                course_id, user, section_descriptor, depth=None)

            section_module = get_module_for_descriptor(
                request.user,
                request,
                section_descriptor,
                section_field_data_cache,
                course_id,
                position
            )

            if section_module is None:
                # User may be trying to be clever and access something
                # they don't have access to.
                raise Http404

            # Save where we are in the chapter
            save_child_position(chapter_module, section)
            context['fragment'] = section_module.render('student_view')
            context['section_title'] = section_descriptor.display_name_with_default
        else:
            # section is none, so display a message
            studio_url = get_studio_url(course_id, 'course')
            prev_section = get_current_child(chapter_module)
            if prev_section is None:
                # Something went wrong -- perhaps this chapter has no sections visible to the user
                raise Http404
            prev_section_url = reverse('courseware_section', kwargs={'course_id': course_id,
                                                                     'chapter': chapter_descriptor.url_name,
                                                                     'section': prev_section.url_name})
            context['fragment'] = Fragment(content=render_to_string(
                'courseware/welcome-back.html',
                {
                    'course': course,
                    'studio_url': studio_url,
                    'chapter_module': chapter_module,
                    'prev_section': prev_section,
                    'prev_section_url': prev_section_url
                }
            ))

        result = render_to_response('courseware/courseware.html', context)
    except Exception as e:
        if isinstance(e, Http404):
            # let it propagate
            raise

        # In production, don't want to let a 500 out for any reason
        if settings.DEBUG:
            raise
        else:
            log.exception(
                u"Error in index view: user={user}, course={course}, chapter={chapter}"
                u" section={section} position={position}".format(
                    user=user,
                    course=course,
                    chapter=chapter,
                    section=section,
                    position=position
                ))
            try:
                result = render_to_response('courseware/courseware-error.html', {
                    'staff_access': staff_access,
                    'course': course
                })
            except:
                # Let the exception propagate, relying on global config to at
                # at least return a nice error message
                log.exception("Error while rendering courseware-error page")
                raise

    return result


@ensure_csrf_cookie
def jump_to_id(request, course_id, module_id):
    """
    This entry point allows for a shorter version of a jump to where just the id of the element is
    passed in. This assumes that id is unique within the course_id namespace
    """

    course_location = CourseDescriptor.id_to_location(course_id)

    items = modulestore().get_items(
        Location('i4x', course_location.org, course_location.course, None, module_id),
        course_id=course_id
    )

    if len(items) == 0:
        raise Http404(
            u"Could not find id: {0} in course_id: {1}. Referer: {2}".format(
                module_id, course_id, request.META.get("HTTP_REFERER", "")
            ))
    if len(items) > 1:
        log.warning(
            u"Multiple items found with id: {0} in course_id: {1}. Referer: {2}. Using first: {3}".format(
                module_id, course_id, request.META.get("HTTP_REFERER", ""), items[0].location.url()
            ))

    return jump_to(request, course_id, items[0].location.url())


@ensure_csrf_cookie
def jump_to(request, course_id, location):
    """
    Show the page that contains a specific location.

    If the location is invalid or not in any class, return a 404.

    Otherwise, delegates to the index view to figure out whether this user
    has access, and what they should see.
    """
    # Complain if the location isn't valid
    try:
        location = Location(location)
    except InvalidLocationError:
        raise Http404("Invalid location")

    # Complain if there's not data for this location
    try:
        (course_id, chapter, section, position) = path_to_location(modulestore(), course_id, location)
    except ItemNotFoundError:
        raise Http404(u"No data at this location: {0}".format(location))
    except NoPathToItem:
        raise Http404(u"This location is not in any class: {0}".format(location))

    # choose the appropriate view (and provide the necessary args) based on the
    # args provided by the redirect.
    # Rely on index to do all error handling and access control.
    if chapter is None:
        return redirect('courseware', course_id=course_id)
    elif section is None:
        return redirect('courseware_chapter', course_id=course_id, chapter=chapter)
    elif position is None:
        return redirect('courseware_section', course_id=course_id, chapter=chapter, section=section)
    else:
        return redirect('courseware_position', course_id=course_id, chapter=chapter, section=section, position=position)


@ensure_csrf_cookie
def course_info(request, course_id):
    """
    Display the course's info.html, or 404 if there is no such course.

    Assumes the course_id is in a valid format.
    """
    course = get_course_with_access(request.user, course_id, 'load')
    staff_access = has_access(request.user, course, 'staff')
    masq = setup_masquerade(request, staff_access)    # allow staff to toggle masquerade on info page
    studio_url = get_studio_url(course_id, 'course_info')
    reverifications = fetch_reverify_banner_info(request, course_id)
    teacher_role = (
        CourseTeacherRole(course.location, None).has_user(request.user)
    )

    context = {
        'request': request,
        'course_id': course_id,
        'cache': None,
        'course': course,
        'staff_access': staff_access,
        'masquerade': masq,
        'studio_url': studio_url,
        'reverifications': reverifications,
        'teacher_role': teacher_role,
    }

    return render_to_response('courseware/info.html', context)


@ensure_csrf_cookie
def static_tab(request, course_id, tab_slug):
    """
    Display the courses tab with the given name.

    Assumes the course_id is in a valid format.
    """
    course = get_course_with_access(request.user, course_id, 'load')

    tab = CourseTabList.get_tab_by_slug(course.tabs, tab_slug)
    if tab is None:
        raise Http404

    contents = get_static_tab_contents(
        request,
        course,
        tab
    )
    if contents is None:
        raise Http404

    return render_to_response('courseware/static_tab.html', {
        'course': course,
        'tab': tab,
        'tab_contents': contents,
    })

# TODO arjun: remove when custom tabs in place, see courseware/syllabus.py


@ensure_csrf_cookie
def syllabus(request, course_id):
    """
    Display the course's syllabus.html, or 404 if there is no such course.

    Assumes the course_id is in a valid format.
    """
    course = get_course_with_access(request.user, course_id, 'load')
    staff_access = has_access(request.user, course, 'staff')

    return render_to_response('courseware/syllabus.html', {
        'course': course,
        'staff_access': staff_access,
    })


def registered_for_course(course, user):
    """
    Return True if user is registered for course, else False
    """
    if user is None:
        return False
    if user.is_authenticated():
        return CourseEnrollment.is_enrolled(user, course.id)
    else:
        return False

def course_api(request, course_id):
    course = get_course(course_id)
    return JsonResponse({ 'display_name': course.display_name_with_default,
                          'display_number': course.display_number_with_default})

@ensure_csrf_cookie
@cache_if_anonymous
def course_about(request, course_id):
    """
    Display the course's about page.

    Assumes the course_id is in a valid format.
    """

    if microsite.get_value(
        'ENABLE_MKTG_SITE',
        settings.FEATURES.get('ENABLE_MKTG_SITE', False)
    ):
        raise Http404

    course = get_course_with_access(request.user, course_id, 'see_exists')
    registered = registered_for_course(course, request.user)
    staff_access = has_access(request.user, course, 'staff')
    studio_url = get_studio_url(course_id, 'settings/details')

    if has_access(request.user, course, 'load'):
        course_target = reverse('info', args=[course.id])
    else:
        course_target = reverse('about_course', args=[course.id])

    show_courseware_link = (has_access(request.user, course, 'load') or
                            settings.FEATURES.get('ENABLE_LMS_MIGRATION'))

    # Note: this is a flow for payment for course registration, not the Verified Certificate flow.
    registration_price = 0
    in_cart = False
    reg_then_add_to_cart_link = ""
    if (settings.FEATURES.get('ENABLE_SHOPPING_CART') and
        settings.FEATURES.get('ENABLE_PAID_COURSE_REGISTRATION')):
        registration_price = CourseMode.min_course_price_for_currency(course_id,
                                                                      settings.PAID_COURSE_REGISTRATION_CURRENCY[0])
        if request.user.is_authenticated():
            cart = shoppingcart.models.Order.get_cart_for_user(request.user)
            in_cart = shoppingcart.models.PaidCourseRegistration.contained_in_order(cart, course_id)

        reg_then_add_to_cart_link = "{reg_url}?course_id={course_id}&enrollment_action=add_to_cart".format(
            reg_url=reverse('register_user'), course_id=course.id)

    # see if we have already filled up all allowed enrollments
    is_course_full = CourseEnrollment.is_course_full(course)
    teacher_role = (
            CourseTeacherRole(course.location, None).has_user(request.user)
        )
    return render_to_response('courseware/course_about.html', {
        'course': course,
        'staff_access': staff_access,
        'studio_url': studio_url,
        'style': 'full',
        'registered': registered,
        'course_target': course_target,
        'registration_price': registration_price,
        'in_cart': in_cart,
        'reg_then_add_to_cart_link': reg_then_add_to_cart_link,
        'show_courseware_link': show_courseware_link,
        'is_course_full': is_course_full,
        'teacher_role': teacher_role,
    })


@ensure_csrf_cookie
@cache_if_anonymous
def mktg_course_about(request, course_id):
    """
    This is the button that gets put into an iframe on the Drupal site
    """

    try:
        course = get_course_with_access(request.user, course_id, 'see_exists')
    except (ValueError, Http404) as e:
        # if a course does not exist yet, display a coming
        # soon button
        return render_to_response(
            'courseware/mktg_coming_soon.html', {'course_id': course_id}
        )

    registered = registered_for_course(course, request.user)

    if has_access(request.user, course, 'load'):
        course_target = reverse('info', args=[course.id])
    else:
        course_target = reverse('about_course', args=[course.id])

    allow_registration = has_access(request.user, course, 'enroll')

    show_courseware_link = (has_access(request.user, course, 'load') or
                            settings.FEATURES.get('ENABLE_LMS_MIGRATION'))
    course_modes = CourseMode.modes_for_course(course.id)
    teacher_role = (
            CourseTeacherRole(course.location, None).has_user(request.user)
        )
    return render_to_response('courseware/mktg_course_about.html', {
        'course': course,
        'registered': registered,
        'allow_registration': allow_registration,
        'course_target': course_target,
        'show_courseware_link': show_courseware_link,
        'course_modes': course_modes,
        'teacher_role': teacher_role,
    })


@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
@transaction.commit_manually
def progress(request, course_id, student_id=None):
    """
    Wraps "_progress" with the manual_transaction context manager just in case
    there are unanticipated errors.
    """
    with grades.manual_transaction():
        return _progress(request, course_id, student_id)


def _progress(request, course_id, student_id):
    """
    Unwrapped version of "progress".

    User progress. We show the grade bar and every problem score.

    Course staff are allowed to see the progress of students in their class.
    """
    course = get_course_with_access(request.user, course_id, 'load', depth=None)
    staff_access = has_access(request.user, course, 'staff')

    if student_id is None or student_id == request.user.id:
        # always allowed to see your own profile
        student = request.user
    else:
        # Requesting access to a different student's profile
        if not staff_access:
            raise Http404
        student = User.objects.get(id=int(student_id))

    # NOTE: To make sure impersonation by instructor works, use
    # student instead of request.user in the rest of the function.

    # The pre-fetching of groups is done to make auth checks not require an
    # additional DB lookup (this kills the Progress page in particular).
    student = User.objects.prefetch_related("groups").get(id=student.id)

    courseware_summary = grades.progress_summary(student, request, course)
    studio_url = get_studio_url(course_id, 'settings/grading')
    grade_summary = grades.grade(student, request, course)

    if courseware_summary is None:
        #This means the student didn't have access to the course (which the instructor requested)
        raise Http404
    teacher_role = (
        CourseTeacherRole(course.location, None).has_user(request.user)
    )
    context = {
        'course': course,
        'courseware_summary': courseware_summary,
        'studio_url': studio_url,
        'grade_summary': grade_summary,
        'staff_access': staff_access,
        'student': student,
        'reverifications': fetch_reverify_banner_info(request, course_id),
        'teacher_role': teacher_role,
    }

    with grades.manual_transaction():
        response = render_to_response('courseware/progress.html', context)

    return response


def fetch_reverify_banner_info(request, course_id):
    """
    Fetches needed context variable to display reverification banner in courseware
    """
    reverifications = defaultdict(list)
    user = request.user
    if not user.id:
        return reverifications
    enrollment = CourseEnrollment.get_or_create_enrollment(request.user, course_id)
    course = course_from_id(course_id)
    info = single_course_reverification_info(user, course, enrollment)
    if info:
        reverifications[info.status].append(info)
    return reverifications


@login_required
def submission_history(request, course_id, student_username, location):
    """Render an HTML fragment (meant for inclusion elsewhere) that renders a
    history of all state changes made by this user for this problem location.
    Right now this only works for problems because that's all
    StudentModuleHistory records.
    """

    course = get_course_with_access(request.user, course_id, 'load')
    staff_access = has_access(request.user, course, 'staff')

    # Permission Denied if they don't have staff access and are trying to see
    # somebody else's submission history.
    if (student_username != request.user.username) and (not staff_access):
        raise PermissionDenied

    try:
        student = User.objects.get(username=student_username)
        student_module = StudentModule.objects.get(
            course_id=course_id,
            module_state_key=location,
            student_id=student.id
        )
    except User.DoesNotExist:
        return HttpResponse(escape(_(u'User {username} does not exist.').format(username=student_username)))
    except StudentModule.DoesNotExist:
        return HttpResponse(escape(_(u'User {username} has never accessed problem {location}').format(
            username=student_username,
            location=location
        )))

    history_entries = StudentModuleHistory.objects.filter(
        student_module=student_module
    ).order_by('-id')

    # If no history records exist, let's force a save to get history started.
    if not history_entries:
        student_module.save()
        history_entries = StudentModuleHistory.objects.filter(
            student_module=student_module
        ).order_by('-id')

    context = {
        'history_entries': history_entries,
        'username': student.username,
        'location': location,
        'course_id': course_id
    }

    return render_to_response('courseware/submission_history.html', context)


def notification_image_for_tab(course_tab, user, course):
    """
    Returns the notification image path for the given course_tab if applicable, otherwise None.
    """

    tab_notification_handlers = {
        StaffGradingTab.type: open_ended_notifications.staff_grading_notifications,
        PeerGradingTab.type: open_ended_notifications.peer_grading_notifications,
        OpenEndedGradingTab.type: open_ended_notifications.combined_notifications
    }

    if course_tab.type in tab_notification_handlers:
        notifications = tab_notification_handlers[course_tab.type](course, user)
        if notifications and notifications['pending_grading']:
            return notifications['img_path']

    return None


def get_static_tab_contents(request, course, tab):
    """
    Returns the contents for the given static tab
    """
    loc = Location(
        course.location.tag,
        course.location.org,
        course.location.course,
        tab.type,
        tab.url_slug,
    )
    field_data_cache = FieldDataCache.cache_for_descriptor_descendents(
        course.id, request.user, modulestore().get_instance(course.id, loc), depth=0
    )
    tab_module = get_module(
        request.user, request, loc, field_data_cache, course.id, static_asset_path=course.static_asset_path
    )

    logging.debug('course_module = {0}'.format(tab_module))

    html = ''
    if tab_module is not None:
        try:
            html = tab_module.render('student_view').content
        except Exception:  # pylint: disable=broad-except
            html = render_to_string('courseware/error-message.html', None)
            log.exception(
                u"Error rendering course={course}, tab={tab_url}".format(course=course,tab_url=tab['url_slug'])
            )

    return html
