import hashlib
import uuid
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.jobs.models import Job, JobStatus, JobTask
from apps.notifications.models import Notification, NotificationKind
from apps.reports.models import Report, ReportStatus

from .base import APITestCase, make_image


class JobLifecycleTests(APITestCase):
    def test_job_snapshots_template_and_notifies_cleaner(self):
        job = self.create_job()
        self.assertEqual(len(JobTask.objects.filter(job_id=job["id"])), 15)
        self.assertTrue(Notification.objects.filter(user=self.cleaner, kind=NotificationKind.JOB_ASSIGNED).exists())

    def test_cleaner_detail_hides_customer_contact_but_has_access_notes(self):
        job = self.create_job()
        data = self.client_for(self.cleaner).get(f"/api/v1/jobs/{job['id']}/").data
        self.assertEqual(data["property_detail"]["access_notes"], "Lockbox 1234")
        self.assertNotIn("alice@host.test", str(data))

    def test_full_offline_flow_produces_final_report(self):
        job = self.create_job()
        client = self.client_for(self.cleaner)
        tasks = JobTask.objects.filter(job_id=job["id"])
        photo_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        issue_id = str(uuid.uuid4())
        t0 = timezone.now() - timedelta(hours=2)

        mutations = [self.mutation("job.start", job["id"], {"latitude": 38.7223, "longitude": -9.1393}, ts=t0)]
        mutations += [
            self.mutation(
                "task.update", job["id"], {"task_id": str(t.id), "status": "done"}, ts=t0 + timedelta(minutes=i + 1)
            )
            for i, t in enumerate(tasks)
        ]
        mutations.append(
            self.mutation(
                "issue.upsert",
                job["id"],
                {
                    "id": issue_id,
                    "room": "Bedroom",
                    "description": "Large stain already present on carpet",
                    "severity": "medium",
                    "phase": "before_cleaning",
                },
                ts=t0 + timedelta(minutes=30),
            )
        )
        mutations.append(
            self.mutation(
                "job.finish", job["id"], {"photo_ids": photo_ids, "notes": "All good"}, ts=t0 + timedelta(minutes=90)
            )
        )
        results = self.push(client, *mutations)
        self.assertTrue(all(r["status"] == "applied" for r in results), results)

        job_obj = Job.objects.get(pk=job["id"])
        self.assertEqual(job_obj.status, JobStatus.COMPLETED)
        self.assertEqual(job_obj.duration_minutes, 90)
        report = Report.objects.get(job=job_obj)
        # Photos haven't arrived yet: report exists but is not final.
        self.assertEqual(report.status, ReportStatus.PENDING_EVIDENCE)
        self.assertEqual(report.content_hash, "")

        self.assertEqual(self.upload_photo(client, job["id"], photo_ids[0], kind="before").status_code, 201)
        r = self.upload_photo(client, job["id"], photo_ids[1], issue=issue_id, kind="issue")
        self.assertEqual(r.status_code, 201, r.data)

        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.FINAL)
        self.assertEqual(len(report.content_hash), 64)
        self.assertEqual(report.snapshot["summary"]["photos"], 2)
        self.assertEqual(report.snapshot["summary"]["tasks_done"], 15)
        self.assertTrue(report.snapshot["job"]["location_verified"])
        self.assertTrue(Notification.objects.filter(user=self.owner, kind=NotificationKind.REPORT_GENERATED).exists())
        self.assertTrue(report.number.startswith(f"CP-{timezone.now().year}-"))

    def test_finish_rejected_when_required_tasks_pending(self):
        job = self.create_job()
        client = self.client_for(self.cleaner)
        results = self.push(client, self.mutation("job.start", job["id"]), self.mutation("job.finish", job["id"]))
        self.assertEqual(results[1]["status"], "rejected")
        self.assertIn("required", results[1]["detail"])

    def test_cancelled_job_keeps_evidence_but_rejects_finish(self):
        job = self.create_job()
        self.client_for(self.owner).post(f"/api/v1/jobs/{job['id']}/cancel/", {"reason": "Guest stayed"}, format="json")
        task = JobTask.objects.filter(job_id=job["id"]).first()
        results = self.push(
            self.client_for(self.cleaner),
            self.mutation("task.update", job["id"], {"task_id": str(task.id), "status": "done"}),
            self.mutation("job.finish", job["id"], {"force": True}),
        )
        self.assertEqual(results[0]["status"], "applied")
        self.assertEqual(results[1]["status"], "rejected")

    def test_unassigned_cleaner_rejected(self):
        other = self.make_user("other@sparkle.test", "cleaner")
        job = self.create_job()
        results = self.push(self.client_for(other), self.mutation("job.start", job["id"]))
        self.assertEqual(results[0]["status"], "rejected")


class SyncConflictTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.job = self.create_job()
        self.task = JobTask.objects.filter(job_id=self.job["id"]).first()
        self.client_ = self.client_for(self.cleaner)

    def test_replayed_mutation_is_idempotent(self):
        m = self.mutation("task.update", self.job["id"], {"task_id": str(self.task.id), "status": "done"})
        first = self.push(self.client_, m)[0]
        second = self.push(self.client_, m)[0]
        self.assertEqual(first["status"], "applied")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(second["original_status"], "applied")

    def test_last_writer_wins_by_device_time(self):
        now = timezone.now()
        newer = self.mutation("task.update", self.job["id"], {"task_id": str(self.task.id), "status": "done"}, ts=now)
        older = self.mutation(
            "task.update",
            self.job["id"],
            {"task_id": str(self.task.id), "status": "pending"},
            ts=now - timedelta(minutes=5),
        )
        results = self.push(self.client_, newer, older)
        self.assertEqual([r["status"] for r in results], ["applied", "ignored_stale"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")

    def test_bad_task_id_is_rejected_not_crash(self):
        results = self.push(
            self.client_, self.mutation("task.update", self.job["id"], {"task_id": "nope", "status": "done"})
        )
        self.assertEqual(results[0]["status"], "rejected")

    def test_pull_returns_assigned_jobs_with_tasks(self):
        data = self.client_.get("/api/v1/sync/pull/").data
        self.assertEqual(len(data["jobs"]), 1)
        self.assertEqual(len(data["jobs"][0]["tasks"]), 15)
        self.assertIn(self.job["id"], data["active_job_ids"])
        # The cursor lags "now" so commits racing it are never missed.
        self.assertLess(data["server_time"], timezone.now() - timedelta(seconds=4))

    def test_pull_since_only_returns_changed_jobs(self):
        cursor = (timezone.now() + timedelta(seconds=1)).isoformat()
        self.assertEqual(len(self.client_.get("/api/v1/sync/pull/", {"since": cursor}).data["jobs"]), 0)
        later = timezone.now() + timedelta(seconds=2)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.push(
                self.client_,
                self.mutation("task.update", self.job["id"], {"task_id": str(self.task.id), "status": "done"}),
            )
        self.assertEqual(len(self.client_.get("/api/v1/sync/pull/", {"since": cursor}).data["jobs"]), 1)

    def test_invalid_since_is_400(self):
        self.assertEqual(self.client_.get("/api/v1/sync/pull/", {"since": "yesterday"}).status_code, 400)


class PhotoTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.job = self.create_job()
        self.client_ = self.client_for(self.cleaner)

    def test_upload_is_idempotent(self):
        pid = str(uuid.uuid4())
        r = self.upload_photo(self.client_, self.job["id"], pid)
        self.assertEqual(r.status_code, 201)
        again = self.upload_photo(self.client_, self.job["id"], pid)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.data["thumbnail_url"].startswith("http"))

    def test_checksum_mismatch_rejected(self):
        response = self.upload_photo(self.client_, self.job["id"], sha256="0" * 64)
        self.assertEqual(response.status_code, 400)

    def test_checksum_match_accepted(self):
        raw = make_image()
        response = self.client_.post(
            "/api/v1/photos/",
            {
                "id": str(uuid.uuid4()),
                "job": self.job["id"],
                "captured_at": timezone.now().isoformat(),
                "file": SimpleUploadedFile("p.jpg", raw, content_type="image/jpeg"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_issue_photo_before_issue_synced_returns_conflict(self):
        response = self.upload_photo(self.client_, self.job["id"], issue=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 409)

    def test_non_image_rejected(self):
        response = self.client_.post(
            "/api/v1/photos/",
            {
                "id": str(uuid.uuid4()),
                "job": self.job["id"],
                "captured_at": timezone.now().isoformat(),
                "file": SimpleUploadedFile("p.jpg", b"not an image", content_type="image/jpeg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_other_cleaner_cannot_upload(self):
        other = self.make_user("x@sparkle.test", "cleaner")
        self.assertEqual(self.upload_photo(self.client_for(other), self.job["id"]).status_code, 403)

    def test_signed_url_serves_file_and_tampering_fails(self):
        data = self.upload_photo(self.client_, self.job["id"]).data
        path = data["thumbnail_url"].replace("http://testserver", "")
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(path[:-3] + "xx/").status_code, 404)

    def test_no_delete_endpoint(self):
        data = self.upload_photo(self.client_, self.job["id"]).data
        response = self.client_for(self.owner).delete(f"/api/v1/photos/{data['id']}/")
        self.assertEqual(response.status_code, 405)
