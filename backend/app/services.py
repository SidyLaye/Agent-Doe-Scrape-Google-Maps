import csv
import hashlib
import io
import re
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import Campaign, Contact, Delivery, Suppression


ALIASES = {
    "business_name": ("business_name", "company", "entreprise", "nom_raison_sociale"),
    "first_name": ("first_name", "prenom", "dirigeant_prenom"),
    "last_name": ("last_name", "nom", "dirigeant_nom", "decision_maker_name"),
    "role": ("role", "fonction", "dirigeant_qualite", "decision_maker_role"),
    "email": ("email", "mail"),
    "phone": ("phone", "telephone", "téléphone"),
    "city": ("city", "ville"),
    "website": ("website", "site", "site_web"),
    "source": ("source", "google_maps_url", "decision_maker_source"),
    "score": ("score", "lead_score", "scoring"),
    "tags": ("tags", "segments", "labels"),
}


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[2:] if digits.startswith("00") else digits


def map_row(row: dict) -> dict:
    lowered = {str(key).strip().lower(): (value or "").strip() for key, value in row.items() if key}
    mapped = {}
    for field, aliases in ALIASES.items():
        mapped[field] = next((lowered[a] for a in aliases if lowered.get(a)), "")
    # Decision-maker exports often keep the full name in one column.
    if not mapped["first_name"] and mapped["last_name"] and " " in mapped["last_name"]:
        parts = mapped["last_name"].split(maxsplit=1)
        mapped["first_name"], mapped["last_name"] = parts[0], parts[1]
    mapped["email"] = mapped["email"].lower()
    mapped["phone"] = normalize_phone(mapped["phone"])
    try: mapped["score"] = max(0, min(100, int(mapped.get("score") or 50)))
    except ValueError: mapped["score"] = 50
    known = {alias for aliases in ALIASES.values() for alias in aliases}
    mapped["custom_data"] = {key: value for key, value in lowered.items() if key not in known and value}
    return mapped


def import_contacts(db: Session, campaign: Campaign, raw: bytes) -> dict:
    text = raw.decode("utf-8-sig")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    added = duplicate = invalid = 0
    suppressions = set(db.scalars(select(Suppression.value)).all())
    for source_row in reader:
        row = map_row(source_row)
        destination = row["email"] or row["phone"]
        if not destination:
            invalid += 1
            continue
        key_source = f"{destination}|{row['business_name']}".lower()
        key = hashlib.sha256(key_source.encode()).hexdigest()
        if db.scalar(select(Contact.id).where(Contact.campaign_id == campaign.id, Contact.dedupe_key == key)):
            duplicate += 1
            continue
        opted_out = row["email"] in suppressions or row["phone"] in suppressions
        db.add(Contact(campaign_id=campaign.id, dedupe_key=key, opted_out=opted_out, **row))
        added += 1
    db.commit()
    return {"added": added, "duplicates": duplicate, "invalid": invalid}


def render(template: str, campaign: Campaign, contact: Contact) -> str:
    values = {
        "business_name": contact.business_name,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "role": contact.role,
        "calendar_url": campaign.calendar_url,
        "video_url": campaign.video_url,
    }
    class Safe(dict):
        def __missing__(self, key): return ""
    return template.format_map(Safe(values)).strip()


def campaign_payload(db: Session, campaign: Campaign) -> dict:
    contacts = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign.id)) or 0
    sent = db.scalar(select(func.count(Delivery.id)).where(Delivery.campaign_id == campaign.id, Delivery.status.in_(("queued", "sent", "delivered", "simulated")))) or 0
    return {**campaign.__dict__, "contact_count": contacts, "sent_count": sent}
