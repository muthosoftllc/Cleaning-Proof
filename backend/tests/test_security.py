"""Regression tests for security hardening. Each test names the attack it blocks."""

import base64
import io
import json
import uuid
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core.http import client_ip
from apps.jobs.models import JobTask, Photo, Signature
from apps.organizations.models import Membership, Organization, Role
from apps.reports.models import Report
from apps.reports.services import generate_pdf

from .base import APITestCase, make_image
from .test_reports_and_billing import ReportFlowMixin


class PdfMarkupInjectionTests(ReportFlowMixin, APITestCase):
    def test_user_text_cannot_embed_server_files_or_break_rendering(self):
        secret = f"{self.media_root}/secret.png"
        Image.new("RGB", (40, 40), "red").save(secret)
        job = self.create_job()
        task = JobTask.objects.filter(job_id=job["id"]).first()
        task.title = "Kitchen <b>unclosed & <i>"
        task.save()
        mutations = [self.mutation("job.start", job["id"])]
        for t in JobTask.objects.filter(job_id=job["id"]):
            note = f'done <img src="{secret}" width="40" height="40"/>' if t.pk == task.pk else ""
            mutations.append(
                self.mutation("task.update", job["id"], {"task_id": str(t.id), "status": "done", "note": note})
            )
        mutations.append(self.mutation("job.finish", job["id"], {"notes": "<para>x</para><img src='http://evil/'>"}))
        self.push(self.client_for(self.cleaner), *mutations)

        report = generate_pdf(Report.objects.get(job_id=job["id"]).pk)
        self.assertTrue(report.pdf, "PDF must render despite hostile markup")
        with report.pdf.open("rb") as fh:
            pdf = fh.read()
        self.assertNotIn(b"/Subtype /Image", pdf)  # no photos uploaded => no images at all


class InputValidationTests(APITestCase):
    def test_garbage_uuid_query_params_are_400_not_500(self):
        client = self.client_for(self.owner)
        for url in [
            "/api/v1/jobs/?property=abc",
            "/api/v1/jobs/?assigned_to=abc",
            "/api/v1/photos/?job=abc",
            "/api/v1/checklists/?property=abc",
            "/api/v1/jobs/?status=bogus",
            "/api/v1/jobs/?from=yesterday",
            "/api/v1/dashboard/?days=abc",
            "/api/v1/dashboard/?days=100000",
        ]:
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 400)

    def test_brand_color_must_be_strict_hex(self):
        # Interpolated into CSS on public pages: '#;}a{b}' would inject rules.
        client = self.client_for(self.owner)
        for bad in ["#;}a{b}", "red", "#12345", "#GGGGGG"]:
            with self.subTest(bad=bad):
                response = client.patch(f"/api/v1/organizations/{self.org.id}/", {"brand_color": bad}, format="json")
                self.assertEqual(response.status_code, 400)
        ok = client.patch(f"/api/v1/organizations/{self.org.id}/", {"brand_color": "#0f766e"}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_timezone_must_exist(self):
        response = self.client_for(self.owner).patch(
            f"/api/v1/organizations/{self.org.id}/", {"timezone": "../../etc/passwd"}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class SyncHardeningTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.job = self.create_job()

    def test_cleaner_cannot_force_finish_with_required_tasks_open(self):
        results = self.push(self.client_for(self.cleaner), self.mutation("job.finish", self.job["id"], {"force": True}))
        self.assertEqual(results[0]["status"], "rejected")

    def test_manager_can_force_finish(self):
        results = self.push(self.client_for(self.owner), self.mutation("job.finish", self.job["id"], {"force": True}))
        self.assertEqual(results[0]["status"], "applied")

    def test_mutation_ids_are_scoped_per_user(self):
        # Previously a global PK: reusing another user's id caused a 500.
        task = JobTask.objects.filter(job_id=self.job["id"]).first()
        m = self.mutation("task.update", self.job["id"], {"task_id": str(task.id), "status": "done"})
        self.assertEqual(self.push(self.client_for(self.cleaner), m)[0]["status"], "applied")
        m2 = {
            **m,
            "client_timestamp": timezone.now().isoformat(),
            "payload": {"task_id": str(task.id), "status": "pending"},
        }
        self.assertEqual(self.push(self.client_for(self.owner), m2)[0]["status"], "applied")

    def test_payloads_are_validated(self):
        client = self.client_for(self.cleaner)
        cases = [
            ("issue.upsert", {"id": str(uuid.uuid4()), "description": "x", "severity": "apocalyptic"}),
            ("issue.upsert", {"id": "not-a-uuid", "description": "x"}),
            ("job.notes", {"notes": "x" * 5001}),
            ("job.finish", {"photo_ids": ["not-a-uuid"]}),
            ("job.start", {"latitude": 123.0}),
            ("task.update", {"task_id": str(uuid.uuid4()), "status": "done"}),
        ]
        for type_, payload in cases:
            with self.subTest(type_=type_, payload=str(payload)[:40]):
                self.assertEqual(
                    self.push(client, self.mutation(type_, self.job["id"], payload))[0]["status"], "rejected"
                )

    def test_outsider_cannot_probe_jobs(self):
        other_org = Organization.objects.create(name="Other")
        outsider = self.make_user("out@other.test", Role.OWNER, org=other_org)
        results = self.push(self.client_for(outsider, org=other_org), self.mutation("job.start", self.job["id"]))
        self.assertEqual(results[0]["status"], "rejected")
        response = self.upload_photo(self.client_for(outsider, org=other_org), self.job["id"])
        self.assertEqual(response.status_code, 404)


class PhotoUploadHardeningTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.job = self.create_job()
        self.client_ = self.client_for(self.cleaner)

    def _upload(self, raw, name="p.jpg"):
        return self.client_.post(
            "/api/v1/photos/",
            {
                "id": str(uuid.uuid4()),
                "job": self.job["id"],
                "captured_at": timezone.now().isoformat(),
                "file": SimpleUploadedFile(name, raw, content_type="image/jpeg"),
            },
            format="multipart",
        )

    def test_disallowed_formats_rejected(self):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, format="GIF")
        self.assertEqual(self._upload(buf.getvalue(), "x.gif").status_code, 400)

    def test_png_kept_with_true_extension(self):
        response = self._upload(make_image(fmt="PNG"), "lying-name.jpg")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Photo.objects.get(pk=response.data["id"]).file.name.endswith(".png"))

    def test_malformed_checksum_rejected(self):
        response = self.client_.post(
            "/api/v1/photos/",
            {
                "id": str(uuid.uuid4()),
                "job": self.job["id"],
                "captured_at": timezone.now().isoformat(),
                "file": SimpleUploadedFile("p.jpg", make_image()),
                "sha256": "zz",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)


class SessionTests(APITestCase):
    def _login(self, email="owner@sparkle.test"):
        return APIClient().post("/api/v1/auth/login/", {"email": email, "password": "Str0ng-pass!"}, format="json").data

    def test_logout_revokes_refresh_token(self):
        tokens = self._login()
        # Works without an access token (it may have expired while offline).
        client = APIClient()
        self.assertEqual(
            client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}, format="json").status_code, 204
        )
        self.assertEqual(client.post("/api/v1/auth/logout/", {"refresh": "garbage"}, format="json").status_code, 204)
        refresh = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(refresh.status_code, 401)

    def test_account_deletion_revokes_all_sessions(self):
        first, second = self._login(), self._login()
        self.client_for(self.owner).delete("/api/v1/auth/me/")
        for tokens in (first, second):
            refresh = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
            self.assertEqual(refresh.status_code, 401)


class ClientIpTests(APITestCase):
    def _request(self, xff):
        return RequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR="10.0.0.9")

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_forwarded_header_ignored_without_trusted_proxy(self):
        # Otherwise anyone could rotate fake IPs to dodge rate limits.
        self.assertEqual(client_ip(self._request("1.2.3.4")), "10.0.0.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_uses_address_appended_by_trusted_proxy(self):
        self.assertEqual(client_ip(self._request("6.6.6.6, 203.0.113.7")), "203.0.113.7")

    def test_public_rate_limit_not_bypassable_with_spoofed_header(self):
        statuses = {
            self.client.get("/r/CP-2026-ZZZZZZ/", HTTP_X_FORWARDED_FOR=f"9.9.9.{i}").status_code for i in range(65)
        }
        self.assertIn(429, statuses)


class HeaderTests(ReportFlowMixin, APITestCase):
    def test_public_page_csp_forbids_inline_script(self):
        report = self.complete_job()
        response = self.client.get(f"/report/{report.share_token}/")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertNotIn("<script>", response.content.decode())

    def test_public_forms_pass_browser_origin_check(self):
        # Real browsers send an Origin header; with a no-referrer policy it is
        # "null" and Django's CSRF check rejects every customer approval.
        report = self.complete_job()
        page = self.client.get(f"/report/{report.share_token}/").content.decode()
        self.assertIn('content="same-origin"', page)
        client = self.client_class(enforce_csrf_checks=True)
        client.get(f"/report/{report.share_token}/")
        token = client.cookies["csrftoken"].value
        response = client.post(
            f"/report/{report.share_token}/approve/",
            {"name": "Alice", "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, 302)

    def test_signed_files_are_sandboxed(self):
        data = self.upload_photo(self.client_for(self.cleaner), self.create_job()["id"]).data
        response = self.client.get(data["url"].replace("http://testserver", ""))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")


class PublicApprovalTests(ReportFlowMixin, APITestCase):
    def test_approval_is_recorded_once(self):
        report = self.complete_job()
        url = f"/report/{report.share_token}/approve/"
        self.client.post(url, {"name": "Alice"})
        self.client.post(url, {"name": "Mallory"})
        report.refresh_from_db()
        self.assertEqual(report.approved_by_name, "Alice")
        self.assertEqual(Signature.objects.filter(job=report.job, source="remote").count(), 1)

    def test_non_png_signature_ignored(self):
        report = self.complete_job()
        jpeg = "data:image/png;base64," + base64.b64encode(make_image(fmt="JPEG")).decode()
        self.client.post(f"/report/{report.share_token}/approve/", {"name": "Alice", "signature": jpeg})
        self.assertEqual(Signature.objects.get(job=report.job).image.name, "")


@override_settings(BILLING_FAKE_VERIFIER=True)
class BillingHardeningTests(APITestCase):
    def test_purchase_token_cannot_inject_api_path(self):
        response = self.client_for(self.owner).post(
            "/api/v1/billing/google-play/verify/",
            {"product_id": "cleaningproof_pro", "purchase_token": "abc/../../edits?x=1"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_product_rejected(self):
        response = self.client_for(self.owner).post(
            "/api/v1/billing/google-play/verify/",
            {"product_id": "free_forever", "purchase_token": f"fake:free_forever:{self.org.id}"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(
        GOOGLE_PLAY_RTDN_AUDIENCE="https://cleaningproof.test/rtdn",
        GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT="pubsub@proj.iam.gserviceaccount.com",
    )
    def test_rtdn_oidc(self):
        token = f"fake:cleaningproof_pro:{self.org.id}"
        body = {
            "message": {
                "data": base64.b64encode(
                    json.dumps({"subscriptionNotification": {"purchaseToken": token}}).encode()
                ).decode()
            }
        }
        url = "/api/v1/billing/google-play/rtdn/"
        self.assertEqual(self.client.post(url, body, content_type="application/json").status_code, 403)
        claims = {"email": "pubsub@proj.iam.gserviceaccount.com", "email_verified": True}
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            ok = self.client.post(url, body, content_type="application/json", HTTP_AUTHORIZATION="Bearer jwt")
        self.assertEqual(ok.status_code, 204)
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value={**claims, "email": "x@evil"}):
            bad = self.client.post(url, body, content_type="application/json", HTTP_AUTHORIZATION="Bearer jwt")
        self.assertEqual(bad.status_code, 403)


class MembershipIsolationTests(APITestCase):
    def test_deactivated_member_loses_access_immediately(self):
        client = self.client_for(self.cleaner)
        self.assertEqual(client.get("/api/v1/jobs/").status_code, 200)
        Membership.objects.filter(user=self.cleaner).update(is_active=False)
        self.assertEqual(client.get("/api/v1/jobs/").status_code, 404)
