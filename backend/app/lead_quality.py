import re
from functools import lru_cache
from urllib.parse import urlparse

import dns.exception
import dns.resolver
import phonenumbers


PLACEHOLDER_DOMAINS = {"email.com", "example.com", "example.org", "domain.com", "test.com", "mail.com"}
PLACEHOLDER_LOCALS = {"email", "test", "example", "yourname", "name", "user", "mail"}
NON_PROSPECTING_LOCALS = {"reclamations", "reclamation", "abuse", "privacy", "dpo", "webmaster", "noreply", "no-reply"}


@lru_cache(maxsize=1000)
def domain_has_mx(domain: str) -> bool | None:
    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 2
        resolver.lifetime = 3
        return bool(resolver.resolve(domain, "MX"))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except (dns.exception.Timeout, OSError):
        return None
    except Exception:
        return None


def validate_email(value: str) -> tuple[str, str]:
    email = (value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", email):
        return "", "email absent ou syntaxe invalide"
    local, domain = email.rsplit("@", 1)
    if domain in PLACEHOLDER_DOMAINS or local in PLACEHOLDER_LOCALS or local in NON_PROSPECTING_LOCALS or local == domain.split(".")[0]:
        return "", "email générique de démonstration rejeté"
    mx_status = domain_has_mx(domain)
    if mx_status is False:
        return "", "domaine email sans serveur MX"
    return email, "email valide avec domaine MX" if mx_status else "syntaxe email valide; contrôle MX temporairement indisponible"


def validate_phone(value: str, country: str = "") -> tuple[str, str]:
    raw = (value or "").strip()
    if not raw:
        return "", "téléphone absent"
    region = {"FR": "FR", "BJ": "BJ", "BENIN": "BJ", "BÉNIN": "BJ"}.get(country.upper(), None)
    try:
        parsed = phonenumbers.parse(raw, region)
        if not phonenumbers.is_valid_number(parsed):
            return "", "numéro de téléphone invalide"
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), "téléphone international valide"
    except Exception:
        return "", "numéro de téléphone invalide"


def website_domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host.removeprefix("www.")


def assess_lead(data: dict) -> dict:
    email, email_note = validate_email(data.get("email", ""))
    phone, phone_note = validate_phone(data.get("phone", ""), data.get("country", ""))
    score = 0
    if data.get("business_name"): score += 10
    if data.get("website"): score += 15
    if phone: score += 25
    if email: score += 30
    if data.get("decision_maker_name"): score += 15
    if data.get("decision_maker_role"): score += 5
    email_domain = email.rsplit("@", 1)[1] if email else ""
    site_domain = website_domain(data.get("website", ""))
    if email_domain and site_domain and (email_domain == site_domain or email_domain.endswith("." + site_domain)):
        score += 10
    score = min(score, 100)
    contactable = bool(email and phone)
    return {
        "email": email,
        "phone": phone,
        "quality_score": score,
        "validation_status": "qualified" if contactable and score >= 70 else "rejected",
        "validation_notes": f"{email_note}; {phone_note}",
    }
