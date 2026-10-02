from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.billing.views import BillingStatusView, GooglePlayRTDNView, GooglePlayVerifyView
from apps.checklists.views import ChecklistTemplateViewSet
from apps.core.views import signed_file
from apps.jobs.dashboard import DashboardView
from apps.jobs.views import JobViewSet, PhotoViewSet, RecurringScheduleViewSet, SyncPullView, SyncPushView
from apps.notifications.views import DeviceView, NotificationViewSet
from apps.organizations.views import (
    AuditEventViewSet, InvitationViewSet, MembershipViewSet, OrganizationViewSet,
)
from apps.properties.views import CustomerViewSet, PropertyViewSet
from apps.reports import views as report_views

router = DefaultRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("members", MembershipViewSet, basename="member")
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("audit-events", AuditEventViewSet, basename="audit-event")
router.register("customers", CustomerViewSet, basename="customer")
router.register("properties", PropertyViewSet, basename="property")
router.register("checklists", ChecklistTemplateViewSet, basename="checklist")
router.register("jobs", JobViewSet, basename="job")
router.register("photos", PhotoViewSet, basename="photo")
router.register("schedules", RecurringScheduleViewSet, basename="schedule")
router.register("reports", report_views.ReportViewSet, basename="report")
router.register("notifications", NotificationViewSet, basename="notification")

api_v1 = [
    path("auth/", include("apps.accounts.urls")),
    path("sync/push/", SyncPushView.as_view(), name="sync-push"),
    path("sync/pull/", SyncPullView.as_view(), name="sync-pull"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("devices/", DeviceView.as_view(), name="devices"),
    path("billing/", BillingStatusView.as_view(), name="billing"),
    path("billing/google-play/verify/", GooglePlayVerifyView.as_view(), name="billing-verify"),
    path("billing/google-play/rtdn/", GooglePlayRTDNView.as_view(), name="billing-rtdn"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("api/v1/", include(api_v1)),
    path("healthz", lambda request: JsonResponse({"ok": True}), name="healthz"),
    path("files/<str:token>/", signed_file, name="signed-file"),
    # Public, no account needed.
    path("r/<str:number>/", report_views.verify_report, name="verify-report"),
    path("report/<str:token>/", report_views.public_report, name="public-report"),
    path("report/<str:token>/pdf/", report_views.public_report_pdf, name="public-report-pdf"),
    path("report/<str:token>/approve/", report_views.public_report_approve, name="public-report-approve"),
    path("report/<str:token>/feedback/", report_views.public_report_feedback, name="public-report-feedback"),
    path("admin/", admin.site.urls),
]
