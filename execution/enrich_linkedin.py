#!/usr/bin/env python3
"""
Enrich leads with director LinkedIn profile URLs via EnrichLayer API.

Flow per lead:
  Person Lookup: first_name + last_name + company_domain -> LinkedIn URL (~2 credits)

Usage:
    python execution/enrich_linkedin.py --first "Jean" --last "Dupont" --domain "example.fr"

Requires ENRICHLAYER_API_KEY in .env
"""

import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://enrichlayer.com/api/v2"
REQUEST_DELAY = 0.5  # seconds between requests (rate limit: 300/min)


def _get_api_key() -> str | None:
    """Get EnrichLayer API key from environment."""
    key = os.getenv("ENRICHLAYER_API_KEY", "")
    if not key:
        return None
    return key


def _api_get(endpoint: str, params: dict) -> dict | None:
    """
    Make a GET request to the EnrichLayer API.
    Returns parsed JSON or None on error.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}{endpoint}?{query}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "GMaps-Lead-Pipeline/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # Profile not found — not an error
        elif e.code == 429:
            print("    Rate limited by EnrichLayer, waiting 10s...")
            time.sleep(10)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None
        elif e.code == 403:
            print("    EnrichLayer: insufficient credits")
            return None
        elif e.code == 401:
            print("    EnrichLayer: invalid API key")
            return None
        else:
            body = e.read().decode("utf-8", errors="replace") if e.readable() else ""
            print(f"    EnrichLayer API error {e.code}: {body[:200]}")
            return None
    except Exception as e:
        print(f"    EnrichLayer request failed: {e}")
        return None


def _clean_first_name(raw: str) -> str:
    """
    Clean a first name from the Annuaire des Entreprises format.

    Problems handled:
      - ALL CAPS: "MICKAEL ROGER ANDRE" -> "Mickael"
      - Multiple prénoms: keep only the first one
      - Accents lost in caps: "CEDRIC" -> "Cedric" (title-case at least)
    """
    if not raw:
        return ""
    # Keep only the first prénom
    first = raw.strip().split()[0]
    # Title-case: CEDRIC -> Cedric, JEAN-PIERRE -> Jean-Pierre
    return first.title()


def _clean_last_name(raw: str) -> str:
    """
    Clean a last name from the Annuaire des Entreprises format.

    Problems handled:
      - ALL CAPS: "CHERFILS (BILLOIR)" -> "Cherfils"
      - Birth name in parens: "DUPONT (MARTIN)" -> "Dupont"
    """
    if not raw:
        return ""
    # Remove parenthetical birth name
    cleaned = re.sub(r'\s*\(.*?\)\s*', '', raw).strip()
    # Title-case
    return cleaned.title()


def _extract_domain(website: str) -> str | None:
    """
    Extract the domain from a website URL.
    'https://www.example.fr/page' -> 'example.fr'
    """
    if not website:
        return None
    domain = website.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.split("/")[0].split("?")[0]
    if not domain or "." not in domain:
        return None
    return domain


def lookup_linkedin_url(first_name: str, last_name: str, company_domain: str) -> str | None:
    """
    Find a person's LinkedIn profile URL from their name and company domain.
    Cost: ~2 credits.
    """
    if not first_name or not last_name or not company_domain:
        return None

    params = {
        "first_name": first_name,
        "last_name": last_name,
        "company_domain": company_domain,
    }

    result = _api_get("/profile/resolve", params)
    if not result:
        return None

    linkedin_url = result.get("url") or result.get("linkedin_profile_url") or result.get("profile_url")
    if linkedin_url and "linkedin.com" in linkedin_url:
        return linkedin_url

    return None


def enrich_linkedin(
    first_name: str = None,
    last_name: str = None,
    website: str = None,
) -> str:
    """
    Find a director's LinkedIn URL from their name + company website.

    Cleans names before lookup:
      "MICKAEL ROGER ANDRE" -> "Mickael"
      "CHERFILS (BILLOIR)" -> "Cherfils"

    Returns:
        LinkedIn URL string, or "" if not found.
    """
    domain = _extract_domain(website)
    if not domain or not first_name or not last_name:
        return ""

    clean_first = _clean_first_name(first_name)
    clean_last = _clean_last_name(last_name)

    if not clean_first or not clean_last:
        return ""

    linkedin_url = lookup_linkedin_url(clean_first, clean_last, domain)
    time.sleep(REQUEST_DELAY)

    return linkedin_url or ""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Find director LinkedIn URL via EnrichLayer")
    parser.add_argument("--first", required=True, help="Director first name")
    parser.add_argument("--last", required=True, help="Director last name")
    parser.add_argument("--domain", help="Company domain (e.g. example.fr)")
    parser.add_argument("--website", help="Company website URL")

    args = parser.parse_args()

    if not _get_api_key():
        print("Error: ENRICHLAYER_API_KEY not found in .env")
        sys.exit(1)

    if not args.domain and not args.website:
        print("Error: provide --domain or --website")
        sys.exit(1)

    domain = args.domain or _extract_domain(args.website)
    result = enrich_linkedin(
        first_name=args.first,
        last_name=args.last,
        website=f"https://{domain}" if args.domain else args.website,
    )

    print(json.dumps({"dirigeant_linkedin": result}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
