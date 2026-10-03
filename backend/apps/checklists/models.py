from django.db import models, transaction

from apps.core.models import BaseModel, OrgScopedModel


class ChecklistTemplate(OrgScopedModel):
    """Reusable checklist, e.g. 'Airbnb Turnover' or 'Standard Residential'.

    ``property`` set means a property-specific checklist.
    """

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="checklists",
    )
    is_archived = models.BooleanField(default=False)

    class Meta(OrgScopedModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name

    @transaction.atomic
    def duplicate(self, name: str | None = None, property=None) -> "ChecklistTemplate":
        copy = ChecklistTemplate.objects.create(
            organization=self.organization,
            name=name or f"{self.name} (copy)",
            description=self.description,
            property=property,
        )
        for section in self.sections.prefetch_related("tasks"):
            new_section = ChecklistSection.objects.create(template=copy, name=section.name, position=section.position)
            ChecklistTask.objects.bulk_create(
                ChecklistTask(
                    section=new_section,
                    title=task.title,
                    instructions=task.instructions,
                    is_required=task.is_required,
                    requires_photo=task.requires_photo,
                    position=task.position,
                )
                for task in section.tasks.all()
            )
        return copy


class ChecklistSection(BaseModel):
    """A room or area: Kitchen, Bathroom, Bedroom..."""

    template = models.ForeignKey(ChecklistTemplate, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=100)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return self.name


class ChecklistTask(BaseModel):
    section = models.ForeignKey(ChecklistSection, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    requires_photo = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return self.title
