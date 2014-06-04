"""
Urls for sysadmin dashboard feature
"""
# pylint: disable=E1120

from django.conf.urls import patterns, url

from dashboard import staff

urlpatterns = patterns(
    '',
    url(r'^$', staff.ImportCert.as_view(), name="staff"),
    url(r'^cert/?$', staff.ImportCert.as_view(), name="staff_cert"),
)
