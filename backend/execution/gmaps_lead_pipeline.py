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
import csv
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Import our modules
from scrape_google_maps import load_apify_dataset, scrape_google_maps
from enrich_dirigeants import enrich_lead
from enrich_linkedin import _clean_first_name, _clean_last_name
from enrich_linkedin_apify import build_linkedin_query, search_linkedin_batch
from outreach import add_outreach_fields, load_templates
from enrich_decision_makers import enrich_decision_makers

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Google Sheets config
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"

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
    "email",
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
    # Country-independent public decision-maker enrichment
    "decision_maker_name",
    "decision_maker_role",
    "decision_maker_linkedin",
    "decision_maker_source",
    "decision_maker_confidence",
    # Outreach: channel, appointment link and ready-to-use messages
    "preferred_channel",
    "booking_url",
    "email_message",
    "sms_message",
    "whatsapp_message",
    "whatsapp_url",
    "outreach_status",
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
        "country": gmaps_data.get("countryCode") or gmaps_data.get("country") or "",
        "phone": gmaps_data.get("phone", ""),
        "email": gmaps_data.get("email", ""),
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
    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", SECRETS_DIR / "token.json"))
    if token_file.exists():
        try:
            with token_file.open('r', encoding='utf-8') as token:
                token_data = json.load(token)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Error loading token: {e}")

    # Some exports contain authorized-user token fields but are delivered under
    # the name credentials.json. Accept that format instead of trying to parse
    # it as an OAuth client configuration.
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(SECRETS_DIR / "credentials.json")))
    if not creds and os.path.exists(creds_file):
        try:
            with open(creds_file, "r", encoding="utf-8-sig") as source:
                credential_data = json.load(source)
            if "refresh_token" in credential_data and "client_id" in credential_data:
                creds = Credentials.from_authorized_user_info(credential_data, SCOPES)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            if not os.path.exists(creds_file):
                print(f"Error: Credentials file '{creds_file}' not found.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        with token_file.open('w', encoding='utf-8') as token:
            token.write(creds.to_json())

    return creds


def ensure_sheet_schema(worksheet) -> None:
    """Append new columns to an existing sheet without moving existing data."""
    headers = worksheet.row_values(1)
    if not headers:
        worksheet.update(values=[LEAD_COLUMNS], range_name="A1")
        return
    missing = [column for column in LEAD_COLUMNS if column not in headers]
    if missing:
        start = len(headers) + 1
        end = start + len(missing) - 1
        worksheet.update(
            values=[missing],
            range_name=f"{gspread.utils.rowcol_to_a1(1, start)}:{gspread.utils.rowcol_to_a1(1, end)}",
        )
        print(f"Added {len(missing)} outreach columns to the existing sheet")


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
        last_header = gspread.utils.rowcol_to_a1(1, len(LEAD_COLUMNS))
        worksheet.format(f'A1:{last_header}', {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
        })
        worksheet.freeze(rows=1)
        is_new = True
        print(f"Created new sheet: {name}")

    ensure_sheet_schema(worksheet)

    return spreadsheet, worksheet, is_new


def get_existing_lead_ids(worksheet) -> set:
    """Get existing lead IDs to avoid duplicates."""
    try:
        lead_ids = worksheet.col_values(1)
        return set(lead_ids[1:])
    except Exception:
        return set()


def export_leads_csv(leads: list[dict], output_path: str) -> str:
    """Export leads locally as an Excel-friendly UTF-8 CSV."""
    output_path = os.path.abspath(output_path)
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow({column: lead.get(column, "") for column in LEAD_COLUMNS})
    return output_path


def run_pipeline(
    search_query: str,
    max_results: int = 10,
    location: str = None,
    sheet_url: str = None,
    sheet_name: str = None,
    booking_url: str = "",
    channel: str = "auto",
    template_file: str = None,
    csv_output: str = None,
    enrich_decisionmakers: bool = False,
    apify_dataset_id: str = None,
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
    templates = load_templates(template_file)

    # Step 1: Scrape Google Maps
    print(f"\nSTEP 1: Scraping Google Maps for '{search_query}'")
    if apify_dataset_id:
        print(f"Reusing Apify dataset {apify_dataset_id}")
        businesses = load_apify_dataset(apify_dataset_id)[:max_results]
    else:
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
        country = (lead.get("country") or "").upper()
        # Only enrich French businesses (also enrich if zip starts with French codes)
        location_is_french = bool(location and "france" in location.lower())
        is_french = country in ("FR", "FRA", "FRANCE") or location_is_french
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

    if enrich_decisionmakers:
        print(f"\nSTEP 3B: Searching public decision-makers")
        try:
            decisionmaker_count = enrich_decision_makers(leads)
        except Exception as exc:
            decisionmaker_count = 0
            results["errors"].append(f"Decision-maker enrichment error: {exc}")
        results["decision_makers_found"] = decisionmaker_count
        print(f"Found {decisionmaker_count}/{len(leads)} decision-maker profiles")

    # Step 4: Prepare outreach messages. Sending remains manual in this MVP.
    print(f"\nSTEP 4: Preparing outreach messages ({channel})")
    for lead in leads:
        lead.update(add_outreach_fields(lead, booking_url, channel, templates))

    # Step 5: Export locally or save to Google Sheets. CSV mode deliberately
    # avoids Google authentication and performs no remote write.
    if csv_output:
        print(f"\nSTEP 5: Exporting to CSV")
        output_path = export_leads_csv(leads, csv_output)
        results["csv_output"] = output_path
        results["leads_added"] = len(leads)
        results["completed_at"] = datetime.now().isoformat()
        print(f"Exported {len(leads)} leads to {output_path}")
        return results

    print(f"\nSTEP 5: Saving to Google Sheet")
    try:
        spreadsheet, worksheet, is_new = get_or_create_sheet(sheet_url, sheet_name)
        results["sheet_url"] = spreadsheet.url
        existing_ids = get_existing_lead_ids(worksheet)
        sheet_columns = worksheet.row_values(1)

        rows = []
        for lead in leads:
            if lead["lead_id"] not in existing_ids:
                # Existing sheets may have received new columns at the end. Use
                # their actual header order so values always stay aligned.
                row = [lead.get(col, "") for col in sheet_columns]
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
    parser.add_argument("--booking-url", default="", help="Calendly or Cal.com booking URL")
    parser.add_argument(
        "--channel", choices=("auto", "email", "sms", "whatsapp"), default="auto",
        help="Preferred outreach channel (default: auto)",
    )
    parser.add_argument("--template-file", help="Optional JSON file overriding message templates")
    parser.add_argument(
        "--csv-output",
        help="Export to a local CSV file instead of writing to Google Sheets",
    )
    parser.add_argument(
        "--enrich-decision-makers", action="store_true",
        help="Search public LinkedIn results for company decision-makers",
    )
    parser.add_argument(
        "--apify-dataset-id",
        help="Reuse an existing Google Maps Apify dataset instead of scraping again",
    )

    args = parser.parse_args()
    results = run_pipeline(
        search_query=args.search,
        max_results=args.limit,
        location=args.location,
        sheet_url=args.sheet_url,
        sheet_name=args.sheet_name,
        booking_url=args.booking_url,
        channel=args.channel,
        template_file=args.template_file,
        csv_output=args.csv_output,
        enrich_decisionmakers=args.enrich_decision_makers,
        apify_dataset_id=args.apify_dataset_id,
    )

    if results["errors"]:
        print(f"Errors occurred: {results['errors']}")


if __name__ == "__main__":
    main()
