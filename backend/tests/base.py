import io
import shutil
import tempfile
import uuid
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.checklists.defaults import create_default_templates
from apps.organizations.models import Membership, Organization, Role
from apps.properties.models import Customer, Property

TEMP_MEDIA = tempfile.mkdtemp(prefix="cp-test-media-")


def make_image(color="red", size=(64, 48), fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@override_settings(MEDIA_ROOT=TEMP_MEDIA, PUBLIC_BASE_URL="https://cleaningproof.test", SECURE_SSL_REDIRECT=False)
class APITestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.org = Organization.objects.create(name="Sparkle Co", contact_email="hi@sparkle.test")
        self.owner = self.make_user("owner@sparkle.test", Role.OWNER)
        self.cleaner = self.make_user("cleaner@sparkle.test", Role.CLEANER, full_name="John Smith")
        self.customer = Customer.objects.create(organization=self.org, name="Alice Host", email="alice@host.test")
        self.templates = create_default_templates(self.org)
        self.template = self.templates[0]
        self.property = Property.objects.create(
            organization=self.org, customer=self.customer, name="Apartment #204",
            address_line1="1 Main St", city="Lisbon", access_notes="Lockbox 1234",
            default_checklist=self.template,
        )

    def make_user(self, email, role=None, org=None, **extra):
        user = User.objects.create_user(email, "Str0ng-pass!", **extra)
        if role:
            Membership.objects.create(organization=org or self.org, user=user, role=role)
        return user

    def client_for(self, user, org=None):
        client = APIClient()
        client.force_authenticate(user)
        client.credentials(HTTP_X_ORGANIZATION=str((org or self.org).id))
        return client

    def create_job(self, client=None, **overrides):
        client = client or self.client_for(self.owner)
        data = {
            "property": str(self.property.id),
            "assigned_to": str(self.cleaner.id),
            "scheduled_start": (timezone.now() + timedelta(hours=1)).isoformat(),
            **overrides,
        }
        response = client.post("/api/v1/jobs/", data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    @staticmethod
    def mutation(type_, job_id, payload=None, ts=None):
        return {
            "id": str(uuid.uuid4()),
            "type": type_,
            "job_id": str(job_id),
            "client_timestamp": (ts or timezone.now()).isoformat(),
            "payload": payload or {},
        }

    def push(self, client, *mutations):
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post("/api/v1/sync/push/", {"mutations": list(mutations)}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["results"]

    def upload_photo(self, client, job_id, photo_id=None, **fields):
        photo_id = photo_id or str(uuid.uuid4())
        data = {
            "id": photo_id,
            "job": str(job_id),
            "file": SimpleUploadedFile("p.jpg", make_image(), content_type="image/jpeg"),
            "captured_at": timezone.now().isoformat(),
            "kind": "after",
            **fields,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return client.post("/api/v1/photos/", data, format="multipart")
