#!/usr/bin/env python3
"""
Clean dirigeant names in an existing Google Sheet.

Fixes:
  - ALL CAPS: "MICKAEL ROGER ANDRE" -> "Mickael"
  - Multiple prénoms: keeps only the first one
  - Birth name in parens: "CHERFILS (BILLOIR)" -> "Cherfils"

Usage:
    python execution/clean_sheet_names.py
"""

import os
import sys
import gspread

# Add execution dir to path so imports work from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from gmaps_lead_pipeline import get_credentials
from enrich_linkedin import _clean_first_name, _clean_last_name

SHEET_NAME = "GMaps Lead Database"


def main():
    print("Connecting to Google Sheets...")
    creds = get_credentials()
    client = gspread.authorize(creds)

    try:
        sheet = client.open(SHEET_NAME)
        worksheet = sheet.sheet1
    except Exception as e:
        print(f"Error opening sheet '{SHEET_NAME}': {e}")
        return

    rows = worksheet.get_all_values()
    if not rows:
        print("Sheet is empty.")
        return

    header = rows[0]
    col_map = {name: i for i, name in enumerate(header)}

    idx_nom = col_map.get("dirigeant_nom")
    idx_prenom = col_map.get("dirigeant_prenom")

    if idx_nom is None or idx_prenom is None:
        print("Error: dirigeant_nom / dirigeant_prenom columns not found.")
        print(f"  Header: {header}")
        return

    # Collect cells to update
    updates = []
    cleaned_count = 0

    for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row (1-based)
        raw_nom = row[idx_nom] if idx_nom < len(row) else ""
        raw_prenom = row[idx_prenom] if idx_prenom < len(row) else ""

        if not raw_nom and not raw_prenom:
            continue

        clean_nom = _clean_last_name(raw_nom)
        clean_prenom = _clean_first_name(raw_prenom)

        changed = False
        if raw_nom and clean_nom != raw_nom:
            col_letter = gspread.utils.rowcol_to_a1(i, idx_nom + 1)
            updates.append({"range": col_letter, "values": [[clean_nom]]})
            changed = True

        if raw_prenom and clean_prenom != raw_prenom:
            col_letter = gspread.utils.rowcol_to_a1(i, idx_prenom + 1)
            updates.append({"range": col_letter, "values": [[clean_prenom]]})
            changed = True

        if changed:
            cleaned_count += 1
            print(f"  Row {i}: {raw_prenom} {raw_nom} -> {clean_prenom} {clean_nom}")

    if not updates:
        print("All names are already clean.")
        return

    print(f"\nUpdating {len(updates)} cells ({cleaned_count} rows)...")
    worksheet.batch_update(updates, value_input_option="RAW")
    print("Done.")


if __name__ == "__main__":
    main()
