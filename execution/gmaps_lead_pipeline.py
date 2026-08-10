#!/usr/bin/env python3
"""
Google Maps Lead Generation Pipeline

End-to-end pipeline that:
1. Scrapes Google Maps for businesses matching search criteria
2. Enriches French businesses with dirigeant (director) data via Annuaire des Entreprises API
3. Enriches dirigeants with LinkedIn profile URLs via Apify Google Search
4. Saves results to a persistent Google Sheet

Usage:
    python gmaps_lead_pipeline.py --search "agences immobilières" --location "Lyon" --limit 10
"""

import os
import sys
import json
import argparse
import hashlib
from datetime import datetime
from dotenv import load_dotenv

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Import our modules
from scrape_google_maps import scrape_google_maps
from enrich_dirigeants import enrich_lead
from enrich_linkedin import _clean_first_name, _clean_last_name
from enrich_linkedin_apify import build_linkedin_query, search_linkedin_batch

load_dotenv()

# Google Sheets config
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Default sheet name for leads
DEFAULT_SHEET_NAME = "GMaps Lead Database"

# Lead schema - columns for the Google Sheet
LEAD_COLUMNS = [
    "lead_id",
    "scraped_at",
    "search_query",
    "business_name",
    "category",
    "address",
    "city",
    "state",
    "zip_code",
    "country",
    "phone",
    "website",
    "google_maps_url",
    "place_id",
    "rating",
    "review_count",
    "price_level",
    # Enrichment: French company director data
    "siren",
    "nom_raison_sociale",
    "dirigeant_nom",
    "dirigeant_prenom",
    "dirigeant_qualite",
    "dirigeant_type",
    # Enrichment: LinkedIn profile
    "dirigeant_linkedin",
]


def generate_lead_id(business_name: str, address: str) -> str:
    """Generate a unique ID for a lead based on name and address."""
    unique_string = f"{business_name}|{address}".lower()
    return hashlib.md5(unique_string.encode()).hexdigest()[:12]


def parse_address(address: str) -> dict:
    """Parse an address string into components."""
    parts = {
        "city": "",
        "state": "",
        "zip_code": "",
        "country": "USA"
    }

    if not address:
        return parts

    import re
    # Try to extract zip code
    zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', address)
    if zip_match:
        parts["zip_code"] = zip_match.group(1)

    # Try to extract state (2-letter code)
    state_match = re.search(r'\b([A-Z]{2})\b', address)
    if state_match:
        parts["state"] = state_match.group(1)

    # City extraction
    if parts["state"]:
        city_match = re.search(rf',\s*([^,]+),?\s*{parts["state"]}', address)
        if city_match:
            parts["city"] = city_match.group(1).strip()

    return parts


def flatten_lead(gmaps_data: dict, search_query: str) -> dict:
    """Flatten Google Maps data into a single lead record."""
    address = gmaps_data.get("address", "")
    addr_parts = parse_address(address)
    
    lead_id = generate_lead_id(
        gmaps_data.get("title", ""),
        address
    )

    return {
        "lead_id": lead_id,
        "scraped_at": datetime.now().isoformat(),
        "search_query": search_query,
        "business_name": gmaps_data.get("title", ""),
        "category": gmaps_data.get("categoryName", ""),
        "address": address,
        "city": addr_parts["city"] or gmaps_data.get("city", ""),
        "state": addr_parts["state"] or gmaps_data.get("state", ""),
        "zip_code": addr_parts["zip_code"] or gmaps_data.get("postalCode", ""),
        "country": gmaps_data.get("countryCode", "USA"),
        "phone": gmaps_data.get("phone", ""),
        "website": gmaps_data.get("website", ""),
        "google_maps_url": gmaps_data.get("url", ""),
        "place_id": gmaps_data.get("placeId", ""),
        "rating": gmaps_data.get("totalScore", ""),
        "review_count": gmaps_data.get("reviewsCount", ""),
        "price_level": gmaps_data.get("price", ""),
    }


def get_credentials():
    """Get OAuth2 credentials for Google Sheets API."""
    creds = None
    if os.path.exists('token.json'):
        try:
            with open('token.json', 'r') as token:
                token_data = json.load(token)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Error loading token: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
            if not os.path.exists(creds_file):
                print(f"Error: Credentials file '{creds_file}' not found.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return creds


def get_or_create_sheet(sheet_url: str = None, sheet_name: str = None) -> tuple:
    """Get existing sheet or create a new one."""
    creds = get_credentials()
    client = gspread.authorize(creds)

    if sheet_url:
        if '/d/' in sheet_url:
            sheet_id = sheet_url.split('/d/')[1].split('/')[0]
        else:
            sheet_id = sheet_url
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        is_new = False
    else:
        name = sheet_name or DEFAULT_SHEET_NAME
        spreadsheet = client.create(name)
        worksheet = spreadsheet.sheet1
        worksheet.update(values=[LEAD_COLUMNS], range_name='A1')
        worksheet.format('A1:X1', {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
        })
        worksheet.freeze(rows=1)
        is_new = True
        print(f"Created new sheet: {name}")

    return spreadsheet, worksheet, is_new


def get_existing_lead_ids(worksheet) -> set:
    """Get existing lead IDs to avoid duplicates."""
    try:
        lead_ids = worksheet.col_values(1)
        return set(lead_ids[1:])
    except Exception:
        return set()


def run_pipeline(
    search_query: str,
    max_results: int = 10,
    location: str = None,
    sheet_url: str = None,
    sheet_name: str = None,
) -> dict:
    """Run the simplified pipeline."""
    results = {
        "search_query": search_query,
        "started_at": datetime.now().isoformat(),
        "businesses_found": 0,
        "leads_added": 0,
        "sheet_url": None,
        "errors": []
    }

    # Step 1: Scrape Google Maps
    print(f"\nSTEP 1: Scraping Google Maps for '{search_query}'")
    businesses = scrape_google_maps(
        search_query=search_query,
        max_results=max_results,
        location=location,
    )

    if not businesses:
        results["errors"].append("No businesses found")
        return results

    results["businesses_found"] = len(businesses)
    print(f"Found {len(businesses)} businesses")

    # Step 2: Enrich with French dirigeant data
    print(f"\nSTEP 2: Enriching with dirigeant data (Annuaire des Entreprises)")
    leads = []
    for b in businesses:
        lead = flatten_lead(b, search_query)
        leads.append(lead)

    enriched_count = 0
    import time
    for i, lead in enumerate(leads):
        name = lead.get("business_name", "")
        zip_code = lead.get("zip_code", "") or None
        if not name:
            continue
        country = lead.get("country", "").upper()
        # Only enrich French businesses (also enrich if zip starts with French codes)
        is_french = country in ("FR", "FRA", "FRANCE", "")
        if not is_french and zip_code and zip_code[:2].isdigit():
            # French zip codes are 5 digits, departments 01-95 + DOM
            dept = int(zip_code[:2])
            if 1 <= dept <= 95 or zip_code[:3] in ("971", "972", "973", "974", "976"):
                is_french = True
        if not is_french:
            continue
        website = lead.get("website", "") or None
        category = lead.get("category", "") or None
        print(f"  [{i+1}/{len(leads)}] {name}", flush=True)
        enrichment = enrich_lead(name, zip_code=zip_code, website=website,
                                 gmaps_category=category)
        lead.update(enrichment)
        # Clean director names for the sheet (CAPS + multiple prénoms -> proper case)
        if lead.get("dirigeant_prenom"):
            lead["dirigeant_prenom"] = _clean_first_name(lead["dirigeant_prenom"])
        if lead.get("dirigeant_nom"):
            lead["dirigeant_nom"] = _clean_last_name(lead["dirigeant_nom"])
        if enrichment.get("siren"):
            enriched_count += 1
        time.sleep(0.1)

    results["leads_enriched"] = enriched_count
    print(f"Enriched {enriched_count}/{len(leads)} leads with dirigeant data")

    # Step 3: Enrich with LinkedIn URLs (LinkedIn native + Google fallback)
    print(f"\nSTEP 3: Searching LinkedIn profiles (native search + Google fallback)")
    linkedin_count = 0
    # Build deduplicated queries for all leads with dirigeant data
    queries_map = {}  # query -> [lead indices]
    lead_query_map = {}  # lead index -> query
    broad_info = {}  # query -> {prenom, nom, city, sector, company}
    for i, lead in enumerate(leads):
        prenom = lead.get("dirigeant_prenom", "")
        nom = lead.get("dirigeant_nom", "")
        dtype = lead.get("dirigeant_type", "")
        if not prenom or not nom or "morale" in dtype.lower():
            continue
        company = lead.get("nom_raison_sociale") or lead.get("business_name", "")
        query = build_linkedin_query(prenom, nom, company)
        if not query:
            continue
        lead_query_map[i] = query
        if query not in queries_map:
            queries_map[query] = []
        queries_map[query].append(i)
        broad_info[query] = {
            "prenom": prenom, "nom": nom,
            "city": lead.get("city", ""),
            "sector": lead.get("category", ""),
            "company": company,
        }

    if queries_map:
        linkedin_results = search_linkedin_batch(queries_map, broad_info=broad_info)
        for i, query in lead_query_map.items():
            url = linkedin_results.get(query, "")
            if url:
                leads[i]["dirigeant_linkedin"] = url
                linkedin_count += 1
    results["leads_linkedin"] = linkedin_count
    print(f"Found {linkedin_count}/{len(lead_query_map)} LinkedIn profiles")

    # Step 4: Save to Google Sheet
    print(f"\nSTEP 4: Saving to Google Sheet")
    try:
        spreadsheet, worksheet, is_new = get_or_create_sheet(sheet_url, sheet_name)
        results["sheet_url"] = spreadsheet.url
        existing_ids = get_existing_lead_ids(worksheet)

        rows = []
        for lead in leads:
            if lead["lead_id"] not in existing_ids:
                row = [lead.get(col, "") for col in LEAD_COLUMNS]
                rows.append(row)
                existing_ids.add(lead["lead_id"])

        if rows:
            worksheet.append_rows(rows, value_input_option='RAW')
            results["leads_added"] = len(rows)
            print(f"Added {len(rows)} new leads to sheet")
        else:
            print("No new leads to add (all duplicates)")

    except Exception as e:
        results["errors"].append(f"Google Sheets error: {str(e)}")
        print(f"Error: {e}")

    results["completed_at"] = datetime.now().isoformat()
    return results


def main():
    parser = argparse.ArgumentParser(description="GMaps to GSheet Pipeline")
    parser.add_argument("--search", required=True, help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--location", help="Location context")
    parser.add_argument("--sheet-url", help="Existing sheet URL")
    parser.add_argument("--sheet-name", help="New sheet name")

    args = parser.parse_args()
    results = run_pipeline(
        search_query=args.search,
        max_results=args.limit,
        location=args.location,
        sheet_url=args.sheet_url,
        sheet_name=args.sheet_name,
    )

    if results["errors"]:
        print(f"Errors occurred: {results['errors']}")


if __name__ == "__main__":
    main()
