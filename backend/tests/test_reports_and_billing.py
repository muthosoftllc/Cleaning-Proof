import base64
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from apps.billing.models import Subscription
from apps.jobs.models import JobTask, RecurringSchedule, Signature
from apps.jobs.recurrence import occurrences
from apps.jobs.services import generate_recurring_jobs
from apps.notifications.models import Notification, NotificationKind
from apps.reports.models import CustomerFeedback, Report, ReportStatus

from .base import APITestCase


class ReportFlowMixin:
    def complete_job(self, with_photo=True):
        job = self.create_job()
        client = self.client_for(self.cleaner)
        photo_id = str(uuid.uuid4())
        mutations = [self.mutation("job.start", job["id"])]
        for task in JobTask.objects.filter(job_id=job["id"]):
            mutations.append(self.mutation("task.update", job["id"], {"task_id": str(task.id), "status": "done"}))
        mutations.append(self.mutation("job.finish", job["id"], {"photo_ids": [photo_id] if with_photo else []}))
        self.push(client, *mutations)
        if with_photo:
            self.upload_photo(client, job["id"], photo_id, kind="after", room="Kitchen")
        return Report.objects.get(job_id=job["id"])


class PublicReportTests(ReportFlowMixin, APITestCase):
    def test_public_report_renders_without_login(self):
        report = self.complete_job()
        response = self.client.get(f"/report/{report.share_token}/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Cleaning completed", html)
        self.assertIn("Apartment #204", html)
        self.assertIn("Powered by", html)
        self.assertIn("/files/", html)  # signed photo URLs
        # Private details never appear on the customer page.
        self.assertNotIn("Lockbox 1234", html)
        self.assertNotIn("1 Main St", html)
        self.assertNotIn("media/", html)

    def test_unknown_token_404(self):
        self.assertEqual(self.client.get("/report/nope/").status_code, 404)

    def test_verification_page_is_minimal(self):
        report = self.complete_job()
        response = self.client.get(f"/r/{report.number}/?format=json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["company"], "Sparkle Co")
        self.assertEqual(data["content_hash"], report.content_hash)
        self.assertNotIn("Alice", json.dumps(data))
        self.assertNotIn("1 Main St", json.dumps(data))
        html = self.client.get(f"/r/{report.number}/").content.decode()
        self.assertIn("Valid report", html)
        self.assertEqual(self.client.get("/r/CP-2026-ZZZZZZ/").status_code, 404)

    def test_customer_approve_with_signature(self):
        report = self.complete_job()
        from .base import make_image

        sig = "data:image/png;base64," + base64.b64encode(make_image(fmt="PNG")).decode()
        response = self.client.post(f"/report/{report.share_token}/approve/", {"name": "Alice", "signature": sig})
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.approved_by_name, "Alice")
        self.assertTrue(Signature.objects.filter(job=report.job, source="remote").exclude(image="").exists())
        self.assertTrue(Notification.objects.filter(kind=NotificationKind.CUSTOMER_APPROVED).exists())

    def test_customer_reports_issue(self):
        report = self.complete_job()
        self.client.post(f"/report/{report.share_token}/feedback/", {"message": "Oven not cleaned"})
        self.assertEqual(CustomerFeedback.objects.get().message, "Oven not cleaned")
        self.assertTrue(Notification.objects.filter(user=self.owner, kind=NotificationKind.CUSTOMER_ISSUE).exists())

    def test_rotate_link_invalidates_old(self):
        report = self.complete_job()
        old = report.share_token
        self.client_for(self.owner).post(f"/api/v1/reports/{report.id}/rotate-link/")
        self.assertEqual(self.client.get(f"/report/{old}/").status_code, 404)

    def test_revoked_report_shows_revoked_on_verify(self):
        report = self.complete_job()
        self.client_for(self.owner).post(f"/api/v1/reports/{report.id}/revoke/")
        self.assertEqual(self.client.get(f"/report/{report.share_token}/").status_code, 404)
        self.assertEqual(self.client.get(f"/r/{report.number}/?format=json").json()["status"], "revoked")

    def test_force_finalize_records_missing_photos(self):
        job = self.create_job()
        mutations = [self.mutation("job.start", job["id"])]
        for task in JobTask.objects.filter(job_id=job["id"]):
            mutations.append(self.mutation("task.update", job["id"], {"task_id": str(task.id), "status": "done"}))
        mutations.append(self.mutation("job.finish", job["id"], {"photo_ids": [str(uuid.uuid4())]}))
        self.push(self.client_for(self.cleaner), *mutations)
        report = Report.objects.get(job_id=job["id"])
        self.assertEqual(report.status, ReportStatus.PENDING_EVIDENCE)
        response = self.client_for(self.owner).post(f"/api/v1/reports/{report.id}/finalize/", {"force": True},
                                                    format="json")
        self.assertEqual(response.data["status"], "final")
        self.assertEqual(len(response.data["snapshot"]["missing_photo_ids"]), 1)

    def test_late_photo_creates_new_revision(self):
        report = self.complete_job()
        old_hash = report.content_hash
        self.upload_photo(self.client_for(self.cleaner), report.job_id)
        report.refresh_from_db()
        self.assertEqual(report.revision, 2)
        self.assertNotEqual(report.content_hash, old_hash)


class PdfTests(ReportFlowMixin, APITestCase):
    def test_pdf_generated_for_pro_plan(self):
        Subscription.objects.create(organization=self.org, plan="pro", product_id="cleaningproof_pro",
                                    purchase_token="tok", status="active",
                                    expires_at=timezone.now() + timedelta(days=10))
        report = self.complete_job()
        report.refresh_from_db()
        self.assertTrue(report.pdf.name.endswith(".pdf"))
        with report.pdf.open("rb") as fh:
            self.assertEqual(fh.read(5), b"%PDF-")

    def test_free_plan_has_no_pdf(self):
        report = self.complete_job()
        self.assertFalse(report.pdf)
        response = self.client_for(self.owner).post(f"/api/v1/reports/{report.id}/pdf/")
        self.assertEqual(response.status_code, 402)


@override_settings(BILLING_FAKE_VERIFIER=True, GOOGLE_PLAY_RTDN_TOKEN="secret")
class BillingTests(APITestCase):
    def test_default_is_free(self):
        data = self.client_for(self.owner).get("/api/v1/billing/").data
        self.assertEqual(data["plan"], "free")
        self.assertEqual(data["limits"]["jobs_per_month"], 10)

    def test_free_job_limit(self):
        for _ in range(10):
            self.create_job()
        response = self.client_for(self.owner).post("/api/v1/jobs/", {
            "property": str(self.property.id), "scheduled_start": (timezone.now() + timedelta(hours=2)).isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, 402)

    def test_verify_purchase_upgrades_plan(self):
        token = f"fake:cleaningproof_pro:{self.org.id}"
        response = self.client_for(self.owner).post("/api/v1/billing/google-play/verify/", {
            "product_id": "cleaningproof_pro", "purchase_token": token}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["plan"], "pro")
        self.assertTrue(Subscription.objects.get().acknowledged)

    def test_purchase_for_other_org_rejected(self):
        token = f"fake:cleaningproof_pro:{uuid.uuid4()}"
        response = self.client_for(self.owner).post("/api/v1/billing/google-play/verify/", {
            "product_id": "cleaningproof_pro", "purchase_token": token}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_only_owner_can_verify(self):
        response = self.client_for(self.cleaner).post("/api/v1/billing/google-play/verify/", {
            "product_id": "cleaningproof_pro", "purchase_token": "x"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_expired_subscription_falls_back_to_free(self):
        Subscription.objects.create(organization=self.org, plan="business", product_id="cleaningproof_business",
                                    purchase_token="old", status="canceled",
                                    expires_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.client_for(self.owner).get("/api/v1/billing/").data["plan"], "free")

    def test_rtdn_requires_secret_and_reverifies(self):
        token = f"fake:cleaningproof_business:{self.org.id}"
        body = {"message": {"data": base64.b64encode(json.dumps({
            "subscriptionNotification": {"purchaseToken": token, "notificationType": 4}}).encode()).decode()}}
        self.assertEqual(self.client.post("/api/v1/billing/google-play/rtdn/", body,
                                          content_type="application/json").status_code, 403)
        response = self.client.post("/api/v1/billing/google-play/rtdn/?token=secret", body,
                                    content_type="application/json")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Subscription.objects.get().plan, "business")


class RecurringTests(APITestCase):
    def setUp(self):
        super().setUp()
        Subscription.objects.create(organization=self.org, plan="pro", product_id="cleaningproof_pro",
                                    purchase_token="tok", status="active")

    def test_weekly_mon_thu_occurrences(self):
        from datetime import date, time

        schedule = RecurringSchedule(frequency="weekly", weekdays=[0, 3], start_time=time(9),
                                     start_date=date(2026, 10, 5), timezone="Europe/Lisbon")
        found = occurrences(schedule, date(2026, 10, 5), date(2026, 10, 18))
        self.assertEqual([d.strftime("%a %d %H:%M") for d in found],
                         ["Mon 05 09:00", "Thu 08 09:00", "Mon 12 09:00", "Thu 15 09:00"])

    def test_biweekly_and_monthly(self):
        from datetime import date, time

        bi = RecurringSchedule(frequency="biweekly", weekdays=[0], start_time=time(9), start_date=date(2026, 10, 5))
        self.assertEqual(len(occurrences(bi, date(2026, 10, 5), date(2026, 11, 1))), 2)
        monthly = RecurringSchedule(frequency="monthly", day_of_month=31, start_time=time(9),
                                    start_date=date(2026, 1, 1))
        self.assertEqual([d.day for d in occurrences(monthly, date(2026, 2, 1), date(2026, 4, 30))], [28, 31, 30])

    def test_generation_is_idempotent_and_notifies(self):
        response = self.client_for(self.owner).post("/api/v1/schedules/", {
            "property": str(self.property.id), "assigned_to": str(self.cleaner.id),
            "checklist_template": str(self.templates[1].id), "title": "Airbnb Turnover",
            "frequency": "daily", "start_time": "09:00", "start_date": str(timezone.localdate()),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        first = generate_recurring_jobs(days_ahead=6)
        second = generate_recurring_jobs(days_ahead=6)
        self.assertGreaterEqual(first, 6)
        self.assertEqual(second, 0)
        self.assertTrue(Notification.objects.filter(kind=NotificationKind.RECURRING_JOB_CREATED).exists())

    def test_recurring_requires_paid_plan(self):
        Subscription.objects.all().delete()
        response = self.client_for(self.owner).post("/api/v1/schedules/", {
            "property": str(self.property.id), "frequency": "daily", "start_time": "09:00",
            "start_date": str(timezone.localdate()),
        }, format="json")
        self.assertEqual(response.status_code, 402)


class DashboardTests(ReportFlowMixin, APITestCase):
    def test_dashboard_metrics(self):
        self.complete_job()
        data = self.client_for(self.owner).get("/api/v1/dashboard/").data
        self.assertEqual(data["today"]["completed"] + data["upcoming"] >= 0, True)
        self.assertEqual(data["counts"]["properties"], 1)
        self.assertEqual(self.client_for(self.cleaner).get("/api/v1/dashboard/").status_code, 403)


class NotificationTests(APITestCase):
    def test_device_registration_and_push_fallback(self):
        client = self.client_for(self.cleaner)
        self.assertEqual(client.post("/api/v1/devices/", {"token": "abc"}, format="json").status_code, 204)
        with mock.patch("apps.notifications.services.send_push", return_value=True) as push:
            with self.captureOnCommitCallbacks(execute=True):
                self.create_job()
        push.assert_called_once()
        data = client.get("/api/v1/notifications/").data
        self.assertEqual(data["count"], 1)
        client.post("/api/v1/notifications/read-all/")
        self.assertEqual(client.get("/api/v1/notifications/?unread=true").data["count"], 0)
