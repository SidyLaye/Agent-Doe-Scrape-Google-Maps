import unittest

from enrich_decision_makers import _clean_linkedin_url, _parse_result


class DecisionMakerTests(unittest.TestCase):
    def test_parse_linkedin_decision_maker(self):
        match = _parse_result({
            "url": "https://bj.linkedin.com/in/ada-doe?trk=test",
            "title": "Ada Doe - Fondatrice - Example Conseil | LinkedIn",
            "description": "Fondatrice de Example Conseil au Bénin",
        }, "Example Conseil")
        self.assertEqual(match["decision_maker_name"], "Ada Doe")
        self.assertEqual(match["decision_maker_confidence"], "élevée")
        self.assertEqual(match["decision_maker_linkedin"], "https://bj.linkedin.com/in/ada-doe")

    def test_reject_non_decision_maker(self):
        self.assertIsNone(_parse_result({
            "url": "https://linkedin.com/in/person",
            "title": "Personne - Stagiaire",
        }, "Example"))

    def test_reject_company_page(self):
        self.assertEqual(_clean_linkedin_url("https://linkedin.com/company/example"), "")


if __name__ == "__main__":
    unittest.main()
