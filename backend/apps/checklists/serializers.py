from django.db import transaction
from rest_framework import serializers

from apps.core.serializers import OrgRelatedField
from apps.properties.models import Property

from .models import ChecklistSection, ChecklistTask, ChecklistTemplate


class ChecklistTaskSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = ChecklistTask
        fields = ["id", "title", "instructions", "is_required", "requires_photo", "position"]


class ChecklistSectionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    tasks = ChecklistTaskSerializer(many=True, required=False)

    class Meta:
        model = ChecklistSection
        fields = ["id", "name", "position", "tasks"]


class ChecklistTemplateSerializer(serializers.ModelSerializer):
    """Templates are edited as a whole document: sections and tasks are
    replaced in one request, which keeps reordering simple for clients.

    Editing a template never changes jobs already created from it: jobs
    snapshot their tasks at creation time.
    """

    sections = ChecklistSectionSerializer(many=True, required=False)
    property = OrgRelatedField(queryset=Property.objects.all(), allow_null=True, required=False)

    class Meta:
        model = ChecklistTemplate
        fields = ["id", "name", "description", "property", "is_archived", "sections", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    @transaction.atomic
    def create(self, validated_data):
        sections = validated_data.pop("sections", [])
        template = ChecklistTemplate.objects.create(**validated_data)
        self._write_sections(template, sections)
        return template

    @transaction.atomic
    def update(self, instance, validated_data):
        sections = validated_data.pop("sections", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if sections is not None:
            instance.sections.all().delete()
            self._write_sections(instance, sections)
        return instance

    @staticmethod
    def _write_sections(template, sections):
        for s_index, section_data in enumerate(sections):
            tasks = section_data.pop("tasks", [])
            section_data.pop("id", None)
            section_data["position"] = s_index
            section = ChecklistSection.objects.create(template=template, **section_data)
            for t_index, task_data in enumerate(tasks):
                task_data.pop("id", None)
                task_data["position"] = t_index
                ChecklistTask.objects.create(section=section, **task_data)


class DuplicateTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    property = OrgRelatedField(queryset=Property.objects.all(), allow_null=True, required=False)
