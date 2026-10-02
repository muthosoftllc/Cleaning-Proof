from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.organizations.audit import record_event
from apps.organizations.models import Membership, Role

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer, UserSerializer


class AuthThrottleMixin:
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(AuthThrottleMixin, generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []


class LoginView(AuthThrottleMixin, TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class RefreshView(AuthThrottleMixin, TokenRefreshView):
    pass


class MeView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Delete the account (GDPR right to erasure).

        Organizations where this user is the only owner are scheduled for
        deletion; the user record is anonymized rather than hard-deleted so
        completed evidence keeps its integrity.
        """
        user = request.user
        for membership in Membership.objects.filter(user=user, role=Role.OWNER, is_active=True):
            org = membership.organization
            other_owners = org.memberships.filter(role=Role.OWNER, is_active=True).exclude(user=user)
            if not other_owners.exists():
                org.schedule_deletion()
            record_event(request, "account.deleted", user, organization=org)
        Membership.objects.filter(user=user).update(is_active=False)
        user.anonymize()
        return Response(status=status.HTTP_204_NO_CONTENT)
