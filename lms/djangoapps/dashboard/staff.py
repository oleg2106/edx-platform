# -*- coding: utf-8 -*-
import logging
import csv
import os
import StringIO
import codecs
import cStringIO
import datetime

from django.utils.translation import ugettext as _

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.servers.basehttp import FileWrapper
from django.http import HttpResponse, Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.generic.base import TemplateView
from django.views.decorators.http import condition
from django_future.csrf import ensure_csrf_cookie
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import connections
from util.date_utils import strftime_localized
from edxmako.shortcuts import render_to_response
from PyPDF2 import PdfFileWriter, PdfFileReader

import track.views

from xmodule.modulestore.django import modulestore
from xmodule.modulestore.xml import XMLModuleStore
from courseware.courses import get_course_by_id, get_courses
from student.models import user_by_anonymous_id
from util.json_request import JsonResponse
from bulk_email.models import CourseEmail

from django.db.models import Q
from django.contrib.auth.models import User
from django_comment_common.models import Role
import lms.lib.comment_client as cc

log = logging.getLogger(__name__)


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

class StaffDashboardView(TemplateView):
    template_name = 'staff_dashboard.html'

    def __init__(self, **kwargs):
        """
        Initialize base sysadmin dashboard class with modulestore,
        modulestore_type and return msg
        """

        self.def_ms = modulestore()
        self.is_using_mongo = True
        if isinstance(self.def_ms, XMLModuleStore):
            self.is_using_mongo = False
        self.msg = u''
        self.context = {}
        self.datatable = []
        super(StaffDashboardView, self).__init__(**kwargs)

    @method_decorator(ensure_csrf_cookie)
    @method_decorator(login_required)
    @method_decorator(cache_control(no_cache=True, no_store=True,
                                    must_revalidate=True))
    @method_decorator(condition(etag_func=None))
    def dispatch(self, *args, **kwargs):
        return super(StaffDashboardView, self).dispatch(*args, **kwargs)

    def get_courses(self):
        """ Get an iterable list of courses."""

        courses = self.def_ms.get_courses()
        courses = dict([c.id, c] for c in courses)  # no course directory

        return courses

    def return_csv(self, filename, header, data):
        """
        Convenient function for handling the http response of a csv.
        data should be iterable and is used to stream object over http
        """

        csv_file = StringIO.StringIO()
        writer = csv.writer(csv_file, dialect='excel', quotechar='"',
                            quoting=csv.QUOTE_ALL)

        writer.writerow(header)

        # Setup streaming of the data
        def read_and_flush():
            """Read and clear buffer for optimization"""
            csv_file.seek(0)
            csv_data = csv_file.read()
            csv_file.seek(0)
            csv_file.truncate()
            return csv_data

        def csv_data():
            """Generator for handling potentially large CSVs"""
            for row in data:
                writer.writerow(row)
            csv_data = read_and_flush()
            yield csv_data
        response = HttpResponse(csv_data(), mimetype='text/csv')
        response['Content-Disposition'] = 'attachment; filename={0}'.format(
            filename)
        return response

class ImportCert(StaffDashboardView):
    """
    The status view provides a view of staffing and enrollment in
    courses that include an option to download the data as a csv.
    """

    def get(self, request):
        """Displays course Enrollment and staffing course statistics"""

        if not request.user.is_staff:
            raise Http404
        data = []

        courses = self.get_courses()

        context = {
            'msg': self.msg,
            'djangopid': os.getpid(),
            'modeflag': {'certs': 'active-section'},
            'edx_platform_version': getattr(settings, 'EDX_PLATFORM_VERSION_STRING', ''),
        }
        return render_to_response(self.template_name, context)

    def post(self, request):
        """Handle all actions from staffing and enrollment view"""

        action = request.POST.get('action', '')
        track.views.server_track(request, action, {},
                                 page='staffing_sysdashboard')

        courses = self.get_courses()

        courses_map = {}

        for course_id in courses:
            course = get_course_by_id(course_id)
            courses_map[course.display_number_with_default + " " + course.display_name_with_default] = course


        if action == 'import_cert':
            csvfile = request.FILES['csvfile']
            pdffile = request.FILES['pdffile']

            if isinstance(pdffile, InMemoryUploadedFile):
                pdffile.mode = "b"

            if csvfile is None:
                self.msg += "No CSV file<br>"
            if pdffile is None:
                self.msg += "No PDF file<br>"

            if not (csvfile is None or pdffile is None):
                data = UnicodeDictReader(csvfile, delimiter=';', quoting=csv.QUOTE_NONE)
                inputpdf = PdfFileReader(pdffile)

                for i, row in enumerate(data):
                    course_name =  row.get('course_num') + " " + row.get('course_name')
                    email = row.get('email')

                    if course_name not in courses_map:
                        self.msg += u"Line {line}: No course with name {course_name}<br>".format(line = i, course_name = course_name)
                        continue

                    course = courses_map[course_name]

                    output = PdfFileWriter()
                    output.addPage(inputpdf.getPage(i))

                    path = u"/edx/app/edxapp/cert/{course_id}/".format(course_id = course.id.replace('/','_'))

                    if not os.path.exists(path):
                        os.makedirs(path)

                    filename = u"{email}.pdf".format(email = email)
                    with open(os.path.join(path, filename), "wb") as outputStream:
                        output.write(outputStream)

            return self.get(request)

        return self.get(request)

class Email(StaffDashboardView):
    """
    The status view provides a view of staffing and enrollment in
    courses that include an option to download the data as a csv.
    """

    def get(self, request):
        """Displays course Enrollment and staffing course statistics"""

        if not request.user.is_staff:
            raise Http404
        data = []

        courses = self.get_courses()

        self.context.update({
            'msg': self.msg,
            'djangopid': os.getpid(),
            'modeflag': {'email': 'active-section'},
            'edx_platform_version': getattr(settings, 'EDX_PLATFORM_VERSION_STRING', ''),
        })
        return render_to_response(self.template_name, self.context)

    def post(self, request):
        """Handle all actions from staffing and enrollment view"""

        action = request.POST.get('action', '')
        track.views.server_track(request, action, {},
                                 page='staffing_sysdashboard')

        courses = self.get_courses()

        courses_map = {}

        for course_id in courses:
            course = get_course_by_id(course_id)
            courses_map[course.display_number_with_default + " " + course.display_name_with_default] = course


        if action == 'email':
            subject = request.POST.get('subject', '')
            body =  request.POST.get('body', '')
            mail = CourseEmail.create('', request.user, 'allall', subject, body)
            mail.send()
            return JsonResponse({
                    'status': 'success',
                    'msg': _('Your email was successfully queued for sending.')
                })

        return self.get(request)

class StaffSettings(StaffDashboardView):
    """
    The status view provides a view of staffing and enrollment in
    courses that include an option to download the data as a csv.
    """

    def get(self, request):
        """Displays course Enrollment and staffing course statistics"""

        if not request.user.is_staff:
            raise Http404
        data = []

        courses = self.get_courses()

        self.context.update({
            'spammer': request.user.profile.spammer,
            'msg': self.msg,
            'djangopid': os.getpid(),
            'modeflag': {'settings': 'active-section'},
            'edx_platform_version': getattr(settings, 'EDX_PLATFORM_VERSION_STRING', ''),
        })
        return render_to_response(self.template_name, self.context)

    def post(self, request):
        """Handle all actions from staffing and enrollment view"""

        action = request.POST.get('action', '')
        track.views.server_track(request, action, {},
                                 page='staffing_sysdashboard')

        courses = self.get_courses()

        courses_map = {}

        for course_id in courses:
            course = get_course_by_id(course_id)
            courses_map[course.display_number_with_default + " " + course.display_name_with_default] = course


        if action == 'save':
            user = request.user
            if request.POST.get('spammer'):
                user.profile.spammer = True
            else:
                user.profile.spammer = False
            user.profile.save()

            return self.get(request)

        return self.get(request)


class Stat(StaffDashboardView):
    """
    The status view provides a view of staffing and enrollment in
    courses that include an option to download the data as a csv.
    """

    def get(self, request):
        """Displays course Enrollment and staffing course statistics"""

        if not request.user.is_staff:
            raise Http404
        data = []

        courses = self.get_courses()

        self.context.update({
            'msg': self.msg,
            'djangopid': os.getpid(),
            'modeflag': {'stat': 'active-section'},
            'edx_platform_version': getattr(settings, 'EDX_PLATFORM_VERSION_STRING', ''),
            'courses': get_courses(request.user),
            'eval_selected_course': request.POST.get('eval_selected_course'),
            'disc_selected_course': request.POST.get('disc_selected_course'),
        })
        return render_to_response(self.template_name, self.context)

    def post(self, request):
        """Handle all actions from staffing and enrollment view"""

        action = request.POST.get('action', '')
        track.views.server_track(request, action, {},
                                 page='staffing_sysdashboard')

        courses = self.get_courses()

        filename = '/edx/app/edxapp/edx-platform/fullstat.csv'

        if action == 'download_stat_unfiltered':
            return self.return_fullstat_csv('/edx/app/edxapp/edx-platform/fullstat.xls')

        elif action == 'download_stat_filtered':
            self.context['value_error_in_input'] = True
            try:
                register_date_min = None
                register_date_max = None
                if request.POST.get('min_date') != '':
                    register_date_min = datetime.datetime.strptime(request.POST.get('min_date'), "%d/%m/%Y")
                if request.POST.get('max_date') != '':
                    register_date_max = datetime.datetime.strptime(request.POST.get('max_date'), "%d/%m/%Y")
                self.context['value_error_in_input'] = False
                return self.return_filtered_stat_csv(\
                    school_login=request.POST.get('school_login'),\
                    register_date_min=register_date_min,\
                    register_date_max=register_date_max,\
                    account_activated=request.POST.get('activated'),\
                    complete70=request.POST.get('complete70'),\
                    complete100=request.POST.get('complete100')\
                )
            except:
                log.exception('Failed to filter')
                return self.get(request)

        elif action == 'download_eval_stat_filtered':

            self.context['eval_value_error_in_input'] = True
            try:
                eval_date_min = None
                eval_date_max = None

                if request.POST.get('eval_min_date') != '':
                    eval_date_min = datetime.datetime.strptime(request.POST.get('eval_min_date'), "%d/%m/%Y")
                if request.POST.get('eval_max_date') != '':
                    eval_date_max = datetime.datetime.strptime(request.POST.get('eval_max_date'), "%d/%m/%Y")
                self.context['eval_selected_course'] = request.POST.get('eval_selected_course')
                self.context['eval_value_error_in_input'] = False
                return self.return_filtered_eval_stat_csv(\
                    #context,\
                    eval_date_min=eval_date_min,\
                    eval_date_max=eval_date_max,\
                    course=request.POST.get('eval_selected_course')
                )
            except:
                log.exception('Failed to filter')
                return self.get(request)

        elif action == 'download_eval_stat_unfiltered':
            return self.return_filtered_eval_stat_csv()

        elif action == 'download_disc_stat_filtered':
            self.context['disc_value_error_in_input'] = True
            try:
                disc_date_min = None
                disc_date_max = None
                if request.POST.get('disc_min_date') != '':
                    disc_date_min = datetime.datetime.strptime(request.POST.get('disc_min_date'), "%d/%m/%Y")
                if request.POST.get('disc_max_date') != '':
                    disc_date_max = datetime.datetime.strptime(request.POST.get('disc_max_date'), "%d/%m/%Y")
                self.context['disc_value_error_in_input'] = False
                return self.return_filtered_disc_stat_csv(\
                    disc_date_min=disc_date_min,\
                    disc_date_max=disc_date_max,\
                    course=request.POST.get('disc_selected_course')
                )
            except:
                return self.get(request)

        elif action == 'download_disc_stat_unfiltered':
            return self.return_filtered_disc_stat_csv()

        return self.get(request)

    def return_fullstat_csv(self, filename):
        """
        Returns fullstat.csv file.
        """
        wrapper = FileWrapper(file(filename))
        response = HttpResponse(wrapper, content_type='text/xls')
        response['Content-Disposition'] = 'attachment; filename=grade_stat.xls'
        return response

    def return_filtered_stat_csv(self, school_login='', register_date_min=None, register_date_max=None, account_activated=None, complete70=None, complete100=None):
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
        response['Content-Disposition'] = 'attachment; filename="grade_stat.xls"'
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
                            # if no valid date in this field -- pass this line
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

    def return_filtered_eval_stat_csv(self, eval_date_min=None, eval_date_max=None, course=''):
        """
        Returns filtered csv file with info on teacher's work on assessments.
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

        response = HttpResponse(content_type='text/xls')
        response['Content-Disposition'] = 'attachment; filename="eval_stat.xls"'
        writer = csv.writer(response, dialect="excel-tab")
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

    def return_filtered_disc_stat_csv(self, disc_date_min=None, disc_date_max=None, course=''):
        
        response = HttpResponse(content_type='text/xls')
        response['Content-Disposition'] = 'attachment; filename="disc_stat.xls"'
        writer = csv.writer(response, dialect="excel-tab")
        encoding = 'cp1251'

        title_row = [u'Статистика по работе преподавателей в дискуссиях для курса: ']
        header_row = [u'ФИО', u'Количество начатых дискуссий', u'Количество комментариев']

        if course != '':
            title_row.append(course)
            users = User.objects.filter(Q(roles__name = 'Administrator') | Q(roles__name = 'Moderator'), roles__course_id = course)
            writer.writerow([unicode(s).encode(encoding) for s in title_row])
            writer.writerow([unicode(s).encode(encoding) for s in header_row])

            for user in users:
                profiled_user = cc.User(id = user.id)
                profiled_user_tc = 0 if profiled_user['threads_count'] is None else profiled_user['threads_count']
                profiled_user_cc = 0 if profiled_user['comments_count'] is None else profiled_user['comments_count']
                row_to_csv = [user.profile.name, profiled_user_tc, profiled_user_cc]
                writer.writerow([unicode(s).encode(encoding) for s in row_to_csv])
        else:
            title_row.append(u'все курсы')
            users = User.objects.filter(Q(roles__name = 'Administrator') | Q(roles__name = 'Moderator'))
            users_merged = {}

            for user in users:
                profiled_user = cc.User(id = user.id)
                profiled_user_tc = 0 if profiled_user['threads_count'] is None else profiled_user['threads_count']
                profiled_user_cc = 0 if profiled_user['comments_count'] is None else profiled_user['comments_count']

                if user.id in users_merged:
                    users_merged[user.id][1] += profiled_user_tc
                    users_merged[user.id][2] += profiled_user_cc
                else:
                    users_merged[user.id] = [user.profile.name, profiled_user_tc, profiled_user_cc]

            writer.writerow([unicode(s).encode(encoding) for s in title_row])
            writer.writerow([unicode(s).encode(encoding) for s in header_row])
            for user.id in users_merged:
                row_to_csv = users_merged[user.id]
                writer.writerow([unicode(s).encode(encoding) for s in row_to_csv])
            
        return response


def UnicodeDictReader(utf8_data, **kwargs):
    csv_reader = csv.DictReader(utf8_data, **kwargs)
    for row in csv_reader:
        yield dict([(key, unicode(value, 'utf-8')) for key, value in row.iteritems()])