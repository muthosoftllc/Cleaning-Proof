from .base import APITestCase


class ChecklistTests(APITestCase):
    def test_create_with_sections_and_reorder(self):
        client = self.client_for(self.owner)
        data = {"name": "Office", "sections": [
            {"name": "Desk area", "tasks": [{"title": "Desks"}, {"title": "Bins", "is_required": False}]},
            {"name": "Kitchen", "tasks": [{"title": "Sink", "requires_photo": True}]},
        ]}
        created = client.post("/api/v1/checklists/", data, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        sections = created.data["sections"]
        # Reorder sections by sending them back in a new order.
        data["sections"] = list(reversed(data["sections"]))
        updated = client.put(f"/api/v1/checklists/{created.data['id']}/", data, format="json")
        self.assertEqual([s["name"] for s in updated.data["sections"]], ["Kitchen", "Desk area"])
        self.assertEqual(len(sections[0]["tasks"]), 2)

    def test_duplicate_for_property(self):
        client = self.client_for(self.owner)
        response = client.post(f"/api/v1/checklists/{self.template.id}/duplicate/",
                               {"name": "Apt 204 special", "property": str(self.property.id)}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["property"], self.property.id)
        self.assertEqual(len(response.data["sections"]), len(self.template.sections.all()))

    def test_template_edit_does_not_change_existing_job(self):
        job = self.create_job()
        client = self.client_for(self.owner)
        client.put(f"/api/v1/checklists/{self.template.id}/", {"name": "Changed", "sections": []}, format="json")
        detail = client.get(f"/api/v1/jobs/{job['id']}/")
        self.assertEqual(len(detail.data["tasks"]), 15)
