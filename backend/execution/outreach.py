"""Deterministic outreach fields and message generation for lead records."""

import json
import re
from pathlib import Path


DEFAULT_TEMPLATES = {
    "email": (
        "Objet : Une idée pour {business_name}\n\nBonjour {contact_name},\n\n"
        "Nous avons identifié quelques pistes d'amélioration pour {business_name}. "
        "Seriez-vous disponible pour un court échange ?\n\n{booking_cta}"
    ),
    "sms": (
        "Bonjour {contact_name}, j'ai quelques pistes d'amélioration pour "
        "{business_name}. Échange rapide : {booking_url}"
    ),
    "whatsapp": (
        "Bonjour {contact_name} 👋 J'ai préparé quelques pistes d'amélioration "
        "pour {business_name}. Vous pouvez choisir un créneau ici : {booking_url}"
    ),
}


class SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


def load_templates(path: str | None = None) -> dict:
    """Load optional JSON template overrides for email, sms and WhatsApp."""
    templates = DEFAULT_TEMPLATES.copy()
    if not path:
        return templates

    with Path(path).open("r", encoding="utf-8") as handle:
        overrides = json.load(handle)
    if not isinstance(overrides, dict):
        raise ValueError("Le fichier de modèles doit contenir un objet JSON.")
    for channel in templates:
        value = overrides.get(channel)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"Le modèle '{channel}' doit être du texte.")
            templates[channel] = value
    return templates


def normalize_phone(phone: str) -> str:
    """Return a WhatsApp-compatible international phone number when possible."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 10 and digits.startswith("0"):
        digits = "33" + digits[1:]
    return digits


def choose_channel(lead: dict, requested: str = "auto") -> str:
    """Choose a usable channel, while respecting an explicit user choice."""
    if requested != "auto":
        return requested
    if lead.get("email"):
        return "email"
    if lead.get("phone"):
        return "whatsapp"
    return "none"


def add_outreach_fields(
    lead: dict,
    booking_url: str = "",
    requested_channel: str = "auto",
    templates: dict | None = None,
) -> dict:
    """Add outreach metadata and one ready-to-use message per channel."""
    templates = templates or DEFAULT_TEMPLATES
    contact_name = lead.get("dirigeant_prenom") or ""
    if not contact_name:
        contact_name = ""
    values = SafeFormatDict({
        **lead,
        "contact_name": contact_name,
        "booking_url": booking_url,
        "booking_cta": (
            f"Vous pouvez choisir le créneau qui vous convient : {booking_url}"
            if booking_url else ""
        ),
    })

    phone = normalize_phone(lead.get("phone", ""))
    messages = {
        channel: template.format_map(values).strip()
        for channel, template in templates.items()
    }
    return {
        "preferred_channel": choose_channel(lead, requested_channel),
        "booking_url": booking_url,
        "email_message": messages["email"],
        "sms_message": messages["sms"],
        "whatsapp_message": messages["whatsapp"],
        "whatsapp_url": f"https://wa.me/{phone}" if phone else "",
        "outreach_status": "à contacter",
    }
