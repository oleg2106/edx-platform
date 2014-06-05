import logging
import csv
import os
import StringIO

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.generic.base import TemplateView
from django.views.decorators.http import condition
from django_future.csrf import ensure_csrf_cookie
from django.core.files.uploadedfile import InMemoryUploadedFile
from edxmako.shortcuts import render_to_response
from PyPDF2 import PdfFileWriter, PdfFileReader

import track.views

from xmodule.modulestore.django import modulestore
from xmodule.modulestore.xml import XMLModuleStore
from courseware.courses import get_course_by_id

log = logging.getLogger(__name__)


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

            context = {
                'msg': self.msg,
                'djangopid': os.getpid(),
                'modeflag': {'certs': 'active-section'},
                'edx_platform_version': getattr(settings, 'EDX_PLATFORM_VERSION_STRING', ''),
            }
            return render_to_response(self.template_name, context)

        return self.get(request)

def UnicodeDictReader(utf8_data, **kwargs):
    csv_reader = csv.DictReader(utf8_data, **kwargs)
    for row in csv_reader:
        yield dict([(key, unicode(value, 'utf-8')) for key, value in row.iteritems()])