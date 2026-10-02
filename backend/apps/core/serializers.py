from rest_framework import serializers


class OrgRelatedField(serializers.PrimaryKeyRelatedField):
    """PK field whose choices are restricted to the caller's organization.

    Prevents cross-tenant references such as assigning a job to a property
    from another organization.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org = self.context.get("organization")
        if org is None:
            return qs.none()
        return qs.filter(organization=org)
