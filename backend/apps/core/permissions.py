import uuid

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.organizations.models import Membership, Role

ORG_HEADER = "HTTP_X_ORGANIZATION"


def resolve_membership(request) -> Membership:
    """Find the caller's active membership for the organization in the request.

    The client sends ``X-Organization: <uuid>``. If omitted and the user belongs
    to exactly one organization, that one is used.
    """
    cached = getattr(request, "_cp_membership", None)
    if cached is not None:
        return cached

    memberships = Membership.objects.select_related("organization").filter(
        user=request.user, is_active=True, organization__deleted_at__isnull=True
    )
    org_id = request.META.get(ORG_HEADER)
    if org_id:
        try:
            membership = memberships.get(organization_id=uuid.UUID(org_id))
        except (Membership.DoesNotExist, ValueError):
            raise NotFound("Organization not found.")
    else:
        found = list(memberships[:2])
        if len(found) != 1:
            raise ValidationError({"detail": "Send the X-Organization header."})
        membership = found[0]
    request._cp_membership = membership
    return membership


class OrgRolePermission(BasePermission):
    """Role-based access inside an organization.

    Views declare ``read_roles`` and ``write_roles``; an action may override
    either through ``action_roles = {"action_name": {...}}``.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        membership = resolve_membership(request)
        action_roles = getattr(view, "action_roles", {}).get(getattr(view, "action", None))
        if action_roles is not None:
            allowed = action_roles
        elif request.method in SAFE_METHODS:
            allowed = getattr(view, "read_roles", Role.ALL)
        else:
            allowed = getattr(view, "write_roles", Role.MANAGERS)
        if membership.role not in allowed:
            raise PermissionDenied("Your role does not allow this action.")
        return True
