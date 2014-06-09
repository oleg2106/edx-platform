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
    url(r'^stat/?$', staff.Stat.as_view(), name="staff_stat"),
    url(r'^email/?$', staff.Email.as_view(), name="staff_email"),
    url(r'^settings/?$', staff.StaffSettings.as_view(), name="staff_settings"),
)
