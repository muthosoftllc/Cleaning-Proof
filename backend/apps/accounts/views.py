from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.organizations.audit import record_event
from apps.organizations.models import Membership, Role

from .serializers import EmailTokenObtainPairSerializer, LogoutSerializer, RegisterSerializer, UserSerializer


def revoke_all_sessions(user) -> None:
    """Blacklist every refresh token ever issued to ``user``."""
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


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


class LogoutView(AuthThrottleMixin, generics.GenericAPIView):
    """Revoke a refresh token. Holding the token is the authority to revoke it,
    so no access token is needed (it may already have expired offline). The
    short-lived access token simply expires; clients drop it immediately."""

    serializer_class = LogoutSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            pass  # already invalid or revoked: nothing to do
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        revoke_all_sessions(user)
        user.anonymize()
        return Response(status=status.HTTP_204_NO_CONTENT)
