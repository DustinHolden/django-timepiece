import json
import datetime
import urllib
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse

from timepiece import models as timepiece
from timepiece import utils
from timepiece.tests.base import TimepieceDataTestCase


class ProjectHoursTestCase(TimepieceDataTestCase):

    def setUp(self):
        self.user = self.create_user('user', 'u@abc.com', 'abc')
        permissions = Permission.objects.filter(
            content_type=ContentType.objects.get_for_model(timepiece.Entry),
            codename__in=('can_clock_in', 'can_clock_out', 'can_pause',
                    'change_entry')
        )
        self.user.user_permissions = permissions
        self.user.save()
        self.superuser = self.create_user('super', 's@abc.com', 'abc', True)

        self.tracked_status = self.create_project_status(data={
                'label': 'Current', 'billable': True,
                'enable_timetracking': True})
        self.untracked_status = self.create_project_status(data={
                'label': 'Closed', 'billable': False,
                'enable_timetracking': False})
        self.tracked_type = self.create_project_type(data={
                'label': 'Tracked', 'billable': True,
                'enable_timetracking': True})
        self.untracked_type = self.create_project_type(data={
                'label': 'Untracked', 'billable': False,
                'enable_timetracking': False})

        self.work_activities = self.create_activity_group('Work')
        self.leave_activities = self.create_activity_group('Leave')
        self.all_activities = self.create_activity_group('All')

        self.leave_activity = self.create_activity(
            activity_groups=[self.leave_activities, self.all_activities],
            data={'code': 'leave', 'name': 'Leave', 'billable': False}
        )
        self.work_activity = self.create_activity(
            activity_groups=[self.work_activities, self.all_activities],
            data={'code': 'work', 'name': 'Work', 'billable': True}
        )

        data = {
            'type': self.tracked_type,
            'status': self.tracked_status,
            'activity_group': self.work_activities,
        }
        self.tracked_project = self.create_project(True, 'Tracked', data)
        data = {
            'type': self.untracked_type,
            'status': self.untracked_status,
            'activity_group': self.all_activities,
        }
        self.untracked_project = self.create_project(True, 'Untracked', data)


class ProjectHoursModelTestCase(ProjectHoursTestCase):

    def test_week_start(self):
        """week_start should always save to Monday of the given week."""
        monday = datetime.date(2012, 07, 16)
        for i in range(7):
            date = monday + relativedelta(days=i)
            entry = timepiece.ProjectHours.objects.create(
                    week_start=date, project=self.tracked_project,
                    user=self.user)
            self.assertEquals(entry.week_start, monday)
            timepiece.ProjectHours.objects.all().delete()


class ProjectHoursListViewTestCase(ProjectHoursTestCase):

    def setUp(self):
        super(ProjectHoursListViewTestCase, self).setUp()
        self.past_week = utils.get_week_start(datetime.date(2012, 4, 1),
                False)
        self.current_week = utils.get_week_start(add_tzinfo=False)
        for i in range(5):
            self.create_project_hours_entry(self.past_week)
            self.create_project_hours_entry(self.current_week)
        self.url = reverse('project_hours')
        self.client.login(username='user', password='abc')
        self.date_format = '%m/%d/%Y'

    def test_no_permission(self):
        """User must have permission timepiece.can_clock_in to view page."""
        basic_user = self.create_user('basic', 'b@e.com', 'abc')
        self.client.login(username='basic', password='abc')
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, 302)

    def test_permission(self):
        """User must have permission timepiece.can_clock_in to view page."""
        self.assertTrue(self.user.has_perm('timepiece.can_clock_in'))
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, 200)

    def test_default_filter(self):
        """Page shows project hours entries from the current week."""
        data = {}
        response = self.client.get(self.url, data)
        self.assertEquals(response.context['week'], self.current_week)

    def test_week_filter(self):
        """Filter shows all entries from Monday to Sunday of specified week."""
        data = {
            'week_start': self.past_week.strftime(self.date_format),
            'submit': '',
        }
        response = self.client.get(self.url, data)
        self.assertEquals(response.context['week'], self.past_week)

        all_entries = utils.get_project_hours_for_week(self.past_week)
        people = response.context['people']
        projects = response.context['projects']
        count = 0
        for proj_id, name, entries in projects:
            for i in range(len(entries)):
                entry = entries[i]
                if entry:
                    count += 1
                    self.assertTrue(all_entries.filter(project__id=proj_id,
                            user__id=people[i][0], hours=entry).exists())
        self.assertEquals(count, all_entries.count())

    def test_week_filter_midweek(self):
        """Filter corrects mid-week date to Monday of specified week."""
        wednesday = datetime.date(2012, 7, 4)
        monday = utils.get_week_start(wednesday, False)
        data = {
            'week_start': wednesday.strftime(self.date_format),
            'submit': '',
        }
        response = self.client.get(self.url, data)
        self.assertEquals(response.context['week'], monday)

    def test_no_entries(self):
        date = utils.get_week_start(datetime.date(2012, 3, 15), False)
        data = {
            'week_start': date.strftime('%m/%d/%Y'),
            'submit': '',
        }
        response = self.client.get(self.url, data)
        self.assertEquals(len(response.context['projects']), 0)
        self.assertEquals(len(response.context['people']), 0)

    def test_all_people_for_project(self):
        """Each project should list hours for every person."""
        response = self.client.get(self.url)
        projects = response.context['projects']
        people = response.context['people']

        for proj_id, name, entries in projects:
            self.assertEquals(len(entries), len(people))


class ProjectHoursEditTestCase(ProjectHoursTestCase):
    def setUp(self):
        super(ProjectHoursEditTestCase, self).setUp()
        self.permission = Permission.objects.filter(codename='add_projecthours')
        self.manager = self.create_user('manager', 'e@e.com', 'abc')
        self.manager.user_permissions = self.permission
        self.view_url = reverse('edit_project_hours')
        self.ajax_url = reverse('project_hours_ajax_view')
        self.week_start = utils.get_week_start(datetime.date.today())

    def create_project_hours(self):
        """Create project hours data"""
        week_start = utils.get_week_start(datetime.date.today())
        timepiece.ProjectHours.objects.create(
            week_start=week_start, project=self.tracked_project,
            user=self.user, hours="25.0")
        timepiece.ProjectHours.objects.create(
            week_start=week_start, project=self.tracked_project,
            user=self.manager, hours="5.0")

        week_start = week_start + relativedelta(days=7)
        timepiece.ProjectHours.objects.create(
            week_start=week_start, project=self.tracked_project,
            user=self.user, hours="15.0")
        timepiece.ProjectHours.objects.create(
            week_start=week_start, project=self.tracked_project,
            user=self.manager, hours="2.0")

    def ajax_posts(self):
        response = self.client.post(self.ajax_url, data={
            'hours': 5
        })
        self.assertEquals(response.status_code, 500)

        response = self.client.post(self.ajax_url, data={
            'hours': 5,
            'project': self.tracked_project.pk
        })
        self.assertEquals(response.status_code, 500)

        response = self.client.post(self.ajax_url, data={
            'project': self.tracked_project.pk
        })
        self.assertEquals(response.status_code, 500)

        response = self.client.post(self.ajax_url, data={
            'project': self.tracked_project.pk,
            'user': self.manager.pk
        })
        self.assertEquals(response.status_code, 500)

        response = self.client.post(self.ajax_url, data={
            'user': self.manager.pk
        })
        self.assertEquals(response.status_code, 500)

        response = self.client.post(self.ajax_url, data={
            'hours': 5,
            'user': self.manager.pk
        })
        self.assertEquals(response.status_code, 500)

    def test_permission_access(self):
        """
        You must have the permission to view the edit page or
        the ajax page
        """
        self.client.login(username='manager', password='abc')

        response = self.client.get(self.view_url)
        self.assertEquals(response.status_code, 200)

        response = self.client.get(self.ajax_url)
        self.assertEquals(response.status_code, 200)

    def test_no_permission_access(self):
        """
        If you are a regular user, you shouldnt be able to view the edit page
        or request any ajax data
        """
        self.client.login(username='basic', password='abc')

        response = self.client.get(self.view_url)
        self.assertEquals(response.status_code, 302)

        response = self.client.get(self.ajax_url)
        self.assertEquals(response.status_code, 302)

    def test_empty_ajax_call(self):
        """
        An ajax call should return empty data sets when project hours
        do not exist
        """
        self.client.login(username='manager', password='abc')

        response = self.client.get(self.ajax_url)
        self.assertEquals(response.status_code, 200)

        data = json.loads(response.content)

        self.assertEquals(data['project_hours'], [])
        self.assertEquals(data['projects'], [])

    def process_default_call(self, response):
        self.assertEquals(response.status_code, 200)

        data = json.loads(response.content)

        self.assertEquals(len(data['project_hours']), 2)
        self.assertEquals(len(data['projects']), 1)

        self.assertEquals(data['project_hours'][0]['hours'], 25.0)
        self.assertEquals(data['project_hours'][1]['hours'], 5.0)

    def test_default_ajax_call(self):
        """
        An ajax call without any parameters should return the current
        weeks data
        """
        self.client.login(username='manager', password='abc')
        self.create_project_hours()

        response = self.client.get(self.ajax_url)

        self.process_default_call(response)

    def test_default_empty_ajax_call(self):
        """
        An ajax call with the parameter present, but empty value, should
        return the same as a call with no parameter
        """
        self.client.login(username='manager', password='abc')
        self.create_project_hours()

        response = self.client.get(self.ajax_url, data={
            'week_start': ''
        })

        self.process_default_call(response)

    def test_ajax_call_date(self):
        """
        An ajax call with the 'week_of' parameter should return
        the data for that week
        """
        self.client.login(username='manager', password='abc')
        self.create_project_hours()

        date = datetime.datetime.now() + relativedelta(days=7)
        response = self.client.get(self.ajax_url, data={
            'week_start': date.strftime('%Y-%m-%d')
        })
        self.assertEquals(response.status_code, 200)

        data = json.loads(response.content)

        self.assertEquals(len(data['project_hours']), 2)
        self.assertEquals(len(data['projects']), 1)

        self.assertEquals(data['project_hours'][0]['hours'], 15.0)
        self.assertEquals(data['project_hours'][1]['hours'], 2.0)

    def test_ajax_create_successful(self):
        """
        A post request on the ajax url should create a new project
        hour entry and return the entry's pk
        """
        self.client.login(username='manager', password='abc')

        self.assertEquals(timepiece.ProjectHours.objects.count(), 0)

        data = {
            'hours': 5,
            'user': self.manager.pk,
            'project': self.tracked_project.pk,
            'week_start': self.week_start.strftime('%Y-%m-%d')
        }
        response = self.client.post(self.ajax_url, data=data)
        self.assertEquals(response.status_code, 200)

        ph = timepiece.ProjectHours.objects.get()
        self.assertEquals(timepiece.ProjectHours.objects.count(), 1)
        self.assertEquals(int(response.content), ph.pk)
        self.assertEquals(ph.hours, Decimal("5.0"))

    def test_ajax_create_unsuccessful(self):
        """
        If any of the data is missing, the server response should
        be a 500 error
        """
        self.client.login(username='manager', password='abc')

        self.assertEquals(timepiece.ProjectHours.objects.count(), 0)

        self.ajax_posts()

        self.assertEquals(timepiece.ProjectHours.objects.count(), 0)

    def test_ajax_update_successful(self):
        """
        A put request to the url with the correct data should update
        an existing project hour entry
        """
        self.client.login(username='manager', password='abc')

        ph = timepiece.ProjectHours.objects.create(
            hours=Decimal('5.0'),
            project=self.tracked_project,
            user=self.manager
        )

        response = self.client.post(self.ajax_url, data={
            'project': self.tracked_project.pk,
            'user': self.manager.pk,
            'hours': 10,
            'week_start': self.week_start.strftime('%Y-%m-%d')
        })
        self.assertEquals(response.status_code, 200)

        ph = timepiece.ProjectHours.objects.get()
        self.assertEquals(ph.hours, Decimal("10"))

    def test_ajax_update_unsuccessful(self):
        """
        If the request to update is missing data, the server should respond
        with a 500 error
        """
        self.client.login(username='manager', password='abc')

        ph = timepiece.ProjectHours.objects.create(
            hours=Decimal('10.0'),
            project=self.untracked_project,
            user=self.manager
        )

        self.ajax_posts()

        self.assertEquals(timepiece.ProjectHours.objects.count(), 1)
        self.assertEquals(ph.hours, Decimal('10.0'))

    def test_ajax_delete_successful(self):
        """
        A delete request with a valid pk should delete the project
        hours entry from the database
        """
        self.client.login(username='manager', password='abc')

        ph = timepiece.ProjectHours.objects.create(
            hours=Decimal('5.0'),
            project=self.tracked_project,
            user=self.manager
        )

        url = reverse('project_hours_detail_view', args=(ph.pk,))

        response = self.client.delete(url)
        self.assertEquals(response.status_code, 200)

        self.assertEquals(timepiece.ProjectHours.objects.count(), 0)
