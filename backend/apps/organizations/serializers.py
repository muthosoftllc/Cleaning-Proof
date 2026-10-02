from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import AuditEvent, Invitation, Membership, Organization, Role


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id", "name", "logo", "brand_color", "contact_email", "contact_phone",
            "website", "timezone", "role", "created_at",
        ]
        read_only_fields = ["id", "created_at", "role"]

    def get_role(self, org):
        roles = self.context.get("roles_by_org") or {}
        return roles.get(org.id)

    def validate_brand_color(self, value):
        if value and (len(value) != 7 or not value.startswith("#")):
            raise serializers.ValidationError("Use a hex color like #0F766E.")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "is_active", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "token", "expires_at", "accepted_at", "revoked_at", "created_at"]
        read_only_fields = ["id", "token", "expires_at", "accepted_at", "revoked_at", "created_at"]

    def validate_email(self, value):
        return value.lower()

    def validate_role(self, value):
        membership = self.context["membership"]
        if value == Role.OWNER and membership.role != Role.OWNER:
            raise serializers.ValidationError("Only owners can invite owners.")
        return value


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()


class AuditEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.email", default=None)

    class Meta:
        model = AuditEvent
        fields = ["id", "action", "actor", "target_type", "target_id", "metadata", "created_at"]
