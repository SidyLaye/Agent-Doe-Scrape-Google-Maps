import json
import tempfile
import unittest
from pathlib import Path

from outreach import add_outreach_fields, choose_channel, load_templates, normalize_phone
from gmaps_lead_pipeline import export_leads_csv


class OutreachTests(unittest.TestCase):
    def test_french_phone_and_auto_channel(self):
        lead = {"business_name": "Test SARL", "phone": "06 12 34 56 78"}
        fields = add_outreach_fields(lead, "https://cal.com/demo")
        self.assertEqual(normalize_phone(lead["phone"]), "33612345678")
        self.assertEqual(fields["preferred_channel"], "whatsapp")
        self.assertEqual(fields["whatsapp_url"], "https://wa.me/33612345678")
        self.assertIn("https://cal.com/demo", fields["whatsapp_message"])

    def test_email_has_priority_in_auto_mode(self):
        self.assertEqual(choose_channel({"email": "a@example.com", "phone": "0102"}), "email")

    def test_json_template_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "templates.json"
            path.write_text(json.dumps({"sms": "RDV {booking_url}"}), encoding="utf-8")
            templates = load_templates(str(path))
        fields = add_outreach_fields({}, "https://cal.com/x", templates=templates)
        self.assertEqual(fields["sms_message"], "RDV https://cal.com/x")

    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "leads.csv"
            export_leads_csv([{"business_name": "Café Bénin", "phone": "+229 01"}], str(path))
            content = path.read_text(encoding="utf-8-sig")
        self.assertIn("business_name", content)
        self.assertIn("Café Bénin", content)


if __name__ == "__main__":
    unittest.main()
