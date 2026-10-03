from .models import ChecklistSection, ChecklistTask, ChecklistTemplate

STARTER_TEMPLATES = {
    "Standard Residential": {
        "Kitchen": ["Countertops", "Sink", "Stove", "Refrigerator exterior", "Floor", "Cabinets"],
        "Bathroom": ["Toilet", "Sink", "Mirror", "Shower", "Floor"],
        "Bedroom": ["Bed", "Furniture", "Floor", ("Windows", False)],
    },
    "Airbnb Turnover": {
        "Kitchen": ["Dishes washed and put away", "Countertops", "Sink", "Appliances wiped", "Trash emptied", "Floor"],
        "Bathroom": ["Toilet", "Shower/tub", "Sink and mirror", "Fresh towels", "Toiletries restocked", "Floor"],
        "Bedroom": ["Bed made with fresh linens", "Surfaces dusted", "Under bed checked", "Floor"],
        "Living area": ["Surfaces dusted", "Cushions arranged", "Floor vacuumed", "Remote/guide in place"],
        "Final check": ["Windows closed and locked", "Lights off", "Thermostat set", "Keys returned"],
    },
}


def create_default_templates(organization):
    created = []
    for name, sections in STARTER_TEMPLATES.items():
        template = ChecklistTemplate.objects.create(organization=organization, name=name)
        for s_index, (section_name, tasks) in enumerate(sections.items()):
            section = ChecklistSection.objects.create(template=template, name=section_name, position=s_index)
            for t_index, task in enumerate(tasks):
                title, required = task if isinstance(task, tuple) else (task, True)
                ChecklistTask.objects.create(section=section, title=title, is_required=required, position=t_index)
        created.append(template)
    return created
