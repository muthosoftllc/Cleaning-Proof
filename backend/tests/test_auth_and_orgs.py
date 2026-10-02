from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.models import AuditEvent, Invitation, Membership, Organization, Role

from .base import APITestCase


class AuthTests(APITestCase):
    def test_register_creates_owner_org_and_returns_tokens(self):
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "email": "New@Biz.test", "password": "Very-secure-123", "organization_name": "New Biz",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("access", response.data)
        user = User.objects.get(email="new@biz.test")
        self.assertEqual(Membership.objects.get(user=user).role, Role.OWNER)

        login = client.post("/api/v1/auth/login/", {"email": "NEW@biz.test", "password": "Very-secure-123"},
                            format="json")
        self.assertEqual(login.status_code, 200, login.data)
        self.assertIn("refresh", login.data)

    def test_weak_password_rejected(self):
        response = APIClient().post("/api/v1/auth/register/", {"email": "a@b.test", "password": "password"},
                                    format="json")
        self.assertEqual(response.status_code, 400)

    def test_account_deletion_anonymizes_and_schedules_sole_owner_org(self):
        client = self.client_for(self.owner)
        response = client.delete("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 204)
        self.owner.refresh_from_db()
        self.org.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertTrue(self.owner.email.endswith("@deleted.invalid"))
        self.assertIsNotNone(self.org.deleted_at)


class TenancyTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Rival Clean")
        self.rival = self.make_user("rival@rival.test", Role.OWNER, org=self.other_org)

    def test_cannot_use_another_orgs_header(self):
        client = self.client_for(self.rival, org=self.org)
        self.assertEqual(client.get("/api/v1/properties/").status_code, 404)

    def test_lists_are_isolated(self):
        client = self.client_for(self.rival, org=self.other_org)
        self.assertEqual(client.get("/api/v1/properties/").data["count"], 0)
        self.assertEqual(client.get(f"/api/v1/properties/{self.property.id}/").status_code, 404)

    def test_cannot_reference_foreign_property(self):
        client = self.client_for(self.rival, org=self.other_org)
        response = client.post("/api/v1/jobs/", {
            "property": str(self.property.id), "scheduled_start": "2030-01-01T09:00:00Z",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("property", response.data)

    def test_cannot_assign_job_to_non_member(self):
        response = self.client_for(self.owner).post("/api/v1/jobs/", {
            "property": str(self.property.id), "assigned_to": str(self.rival.id),
            "scheduled_start": "2030-01-01T09:00:00Z",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned_to", response.data)

    def test_malformed_org_header(self):
        client = self.client_for(self.owner)
        client.credentials(HTTP_X_ORGANIZATION="not-a-uuid")
        self.assertEqual(client.get("/api/v1/properties/").status_code, 404)


class RoleTests(APITestCase):
    def test_cleaner_cannot_manage_customers_or_properties(self):
        client = self.client_for(self.cleaner)
        self.assertEqual(client.get("/api/v1/customers/").status_code, 403)
        self.assertEqual(client.post("/api/v1/properties/", {"name": "X"}, format="json").status_code, 403)

    def test_cleaner_only_sees_assigned_properties_and_jobs(self):
        from apps.properties.models import Property

        Property.objects.create(organization=self.org, name="Not mine")
        client = self.client_for(self.cleaner)
        self.assertEqual(client.get("/api/v1/properties/").data["count"], 0)
        self.create_job()
        self.create_job(assigned_to=None)
        self.assertEqual(client.get("/api/v1/jobs/").data["count"], 1)
        self.assertEqual(client.get("/api/v1/properties/").data["count"], 1)

    def test_viewer_is_read_only(self):
        viewer = self.make_user("viewer@sparkle.test", Role.VIEWER)
        client = self.client_for(viewer)
        self.assertEqual(client.get("/api/v1/jobs/").status_code, 200)
        self.assertEqual(client.post("/api/v1/customers/", {"name": "Y"}, format="json").status_code, 403)

    def test_last_owner_cannot_be_demoted(self):
        membership = Membership.objects.get(user=self.owner)
        response = self.client_for(self.owner).patch(f"/api/v1/members/{membership.id}/", {"role": "admin"},
                                                    format="json")
        self.assertEqual(response.status_code, 400)


class InvitationTests(APITestCase):
    def test_invite_and_accept(self):
        from apps.billing.models import Subscription

        Subscription.objects.create(organization=self.org, plan="pro", product_id="cleaningproof_pro",
                                    purchase_token="t1", status="active")
        response = self.client_for(self.owner).post("/api/v1/invitations/", {"email": "Maria@x.test"},
                                                    format="json")
        self.assertEqual(response.status_code, 201, response.data)
        maria = self.make_user("maria@x.test")
        client = APIClient()
        client.force_authenticate(maria)
        accept = client.post("/api/v1/invitations/accept/", {"token": response.data["token"]}, format="json")
        self.assertEqual(accept.status_code, 200, accept.data)
        self.assertEqual(Membership.objects.get(user=maria).role, Role.CLEANER)
        self.assertFalse(Invitation.objects.get().is_pending)
        self.assertTrue(AuditEvent.objects.filter(action="invitation.accepted").exists())

    def test_free_plan_member_limit(self):
        # Free plan: 1 non-viewer member; owner + cleaner already exceed it.
        response = self.client_for(self.owner).post("/api/v1/invitations/", {"email": "z@x.test"}, format="json")
        self.assertEqual(response.status_code, 402)

    def test_accept_with_wrong_email_fails(self):
        invitation = Invitation.objects.create(organization=self.org, email="someone@x.test")
        client = self.client_for(self.cleaner)
        response = client.post("/api/v1/invitations/accept/", {"token": invitation.token}, format="json")
        self.assertEqual(response.status_code, 403)
