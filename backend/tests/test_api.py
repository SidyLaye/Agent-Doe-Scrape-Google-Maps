import os
os.environ["DATABASE_URL"] = "sqlite:///./test_ambs.db"
os.environ["DRY_RUN"] = "true"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
login = client.post("/api/auth/login", json={"email": "contact@ambs-agency.com", "password": "AMBS$33sbmA"})
assert login.status_code == 200
client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})


def test_authentication_is_required_and_login_works():
    anonymous = TestClient(app)
    assert anonymous.get("/api/campaigns").status_code == 401
    assert anonymous.post("/api/auth/login", json={"email": "contact@ambs-agency.com", "password": "wrong"}).status_code == 401
    assert client.get("/api/auth/me").json()["email"] == "contact@ambs-agency.com"
    assert client.patch("/api/config/mode", json={"dry_run": False, "confirm_live": False}).status_code == 409


def test_spa_routes_survive_browser_refresh():
    for path in ("/campagnes", "/prospects", "/conversations", "/conformite"):
        response = client.get(path)
        assert response.status_code == 200 and "text/html" in response.headers["content-type"]


def test_campaign_import_preview_and_simulated_send(tmp_path):
    created = client.post("/api/campaigns", json={
        "name": "Test immobilier", "channel": "email", "provider": "emelia",
        "subject": "Une idée pour {business_name}",
        "message": "Bonjour {first_name}, RDV: {calendar_url}",
        "calendar_url": "https://cal.com/test",
    })
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    csv_data = "business_name,email,first_name\nAgence Test,jean@example.com,Jean\n"
    imported = client.post(f"/api/campaigns/{campaign_id}/contacts/import", files={"file": ("contacts.csv", csv_data, "text/csv")})
    assert imported.json()["added"] == 1
    preview = client.get(f"/api/campaigns/{campaign_id}/preview").json()
    assert "Jean" in preview["message"] and "cal.com/test" in preview["message"]
    sent = client.post(f"/api/campaigns/{campaign_id}/send", json={"limit": 10}).json()
    assert sent["simulated"] == 1


def test_advanced_campaign_sequence_scoring_and_analytics():
    created = client.post("/api/campaigns", json={
        "name": "Décideurs SaaS", "sector": "SaaS", "objective": "book_meeting",
        "tags": "france,ceo", "channel": "whatsapp", "provider": "ambs",
        "message": "Bonjour {first_name}, une idée pour {business_name}: {calendar_url}",
        "calendar_url": "https://cal.com/ambs",
    })
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    step = client.post(f"/api/campaigns/{campaign_id}/sequence", json={
        "channel": "email", "provider": "emelia", "delay_hours": 48,
        "subject": "Relance", "message": "Avez-vous vu ma proposition ?",
    })
    assert step.status_code == 201 and step.json()["position"] == 1
    csv_data = "business_name,phone,first_name,score,tags,employee_count\nAMBS,+33600000000,Ada,92,saas;ceo,25\n"
    imported = client.post(f"/api/campaigns/{campaign_id}/contacts/import", files={"file": ("audience.csv", csv_data, "text/csv")})
    assert imported.json()["added"] == 1
    contacts = client.get(f"/api/campaigns/{campaign_id}/contacts?min_score=80").json()
    assert contacts[0]["score"] == 92 and contacts[0]["tags"] == "saas;ceo"
    analytics = client.get("/api/analytics")
    assert analytics.status_code == 200 and analytics.json()["campaigns"] >= 1


def test_prospects_are_postgresql_backed_and_assignable():
    from app.database import SessionLocal
    from app.models import Prospect
    import hashlib
    with SessionLocal() as db:
        key = hashlib.sha256(b"test prospect|paris").hexdigest()
        prospect = db.scalar(__import__('sqlalchemy').select(Prospect).where(Prospect.dedupe_key == key))
        if not prospect:
            prospect = Prospect(business_name="Test Prospect", city="Paris", email="contact@test-prospect.fr", phone="+33143961558", email_source="website", score=80, quality_score=80, validation_status="qualified", dedupe_key=key)
            db.add(prospect); db.commit(); db.refresh(prospect)
        prospect.phone = "+33143961558"; prospect.quality_score = 80; prospect.validation_status = "qualified"; db.commit()
        prospect_id = prospect.id
    rows = client.get("/api/prospects?search=Test%20Prospect")
    assert rows.status_code == 200 and rows.json()[0]["email_source"] == "website"
    campaign = client.post("/api/campaigns", json={"name":"Prospect target", "channel":"email", "provider":"emelia", "message":"Bonjour"}).json()
    assigned = client.post("/api/prospects/add-to-campaign", json={"campaign_id":campaign["id"], "prospect_ids":[prospect_id]})
    assert assigned.status_code == 200 and assigned.json()["added"] in (0, 1)
    enriched = client.get("/api/prospects?search=Test%20Prospect").json()[0]
    assert enriched["crm_status"] == "targeted" and enriched["campaign_count"] >= 1
    messages = client.patch(f"/api/prospects/{prospect_id}/messages", json={
        "email_subject": "Test", "email_message": "Email modifié", "whatsapp_message": "WhatsApp modifié", "sms_message": "SMS modifié",
    })
    assert messages.status_code == 200 and messages.json()["sms_message"] == "SMS modifié"


def test_csv_prospect_import_and_campaign_content_type():
    csv_data = "entreprise,email,telephone,ville\nStudio Alpha,hello@alpha.fr,+33102030405,Paris\n"
    imported = client.post("/api/prospects/import", files={"file": ("prospects.csv", csv_data, "text/csv")})
    assert imported.status_code == 200 and imported.json()["emails"] == 1
    campaign = client.post("/api/campaigns", json={"name":"HTML email", "channel":"email", "provider":"emelia", "content_type":"html", "subject":"Bonjour", "message":"<h1>Bonjour {first_name}</h1>"})
    assert campaign.status_code == 201 and campaign.json()["content_type"] == "html"


def test_excel_prospect_import():
    from io import BytesIO
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["entreprise", "prenom", "nom", "fonction", "email", "telephone", "ville", "site", "message sms", "message whatsapp", "message email"])
    sheet.append(["Cabinet Horizon", "Ada", "Houn", "Dirigeante", "direction@horizon.fr", "+2290146688328", "Cotonou", "https://horizon.fr", "Bonjour Ada", "Bonjour Ada sur WhatsApp", "Bonjour Ada par email"])
    content = BytesIO()
    workbook.save(content)
    imported = client.post(
        "/api/prospects/import",
        files={"file": ("prospects.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200 and imported.json()["emails"] == 1
    prospect = client.get("/api/prospects?search=Cabinet%20Horizon").json()[0]
    assert prospect["decision_maker_name"] == "Ada Houn"
    assert prospect["sms_message"] == "Bonjour Ada" and prospect["email_message"] == "Bonjour Ada par email"


def test_sms_length_and_future_scheduling():
    too_long = client.post("/api/campaigns", json={
        "name": "SMS trop long", "channel": "sms", "provider": "isendpro", "message": "x" * 161,
    })
    assert too_long.status_code == 422
    campaign = client.post("/api/campaigns", json={
        "name": "SMS programmé", "channel": "sms", "provider": "isendpro", "message": "Bonjour {first_name}, test AMBS.",
    }).json()
    scheduled = client.post(f"/api/campaigns/{campaign['id']}/schedule", json={
        "scheduled_at": "2099-01-01T10:00:00+00:00", "confirm_live": False,
    })
    assert scheduled.status_code == 200 and scheduled.json()["status"] == "scheduled"


def test_placeholder_email_is_rejected():
    from app.lead_quality import assess_lead
    result = assess_lead({"business_name": "Cabinet KMI", "email": "email@email.com", "phone": "", "website": "https://cabinet-kmi.com"})
    assert result["email"] == "" and result["validation_status"] == "rejected"
