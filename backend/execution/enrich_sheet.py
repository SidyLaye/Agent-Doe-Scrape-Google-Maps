#!/usr/bin/env python3
"""
Enrich existing Google Sheet leads with French company director data.
"""

import os
import sys
import time
import gspread
from datetime import datetime

# Add execution dir to path
sys.path.append(os.path.dirname(__file__))

from gmaps_lead_pipeline import get_credentials, LEAD_COLUMNS
from enrich_dirigeants import enrich_lead

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

    # Get all values including header
    rows = worksheet.get_all_values()
    if not rows:
        print("Sheet is empty.")
        return

    header = rows[0]
    
    # Check if we need to add enrichment columns
    enrichment_cols = [
        "siren", "nom_raison_sociale", "dirigeant_nom", 
        "dirigeant_prenom", "dirigeant_qualite", "dirigeant_type"
    ]
    
    # Map column names to indices
    col_map = {name: i for i, name in enumerate(header)}
    
    # If missing columns, add them
    missing_cols = [c for c in enrichment_cols if c not in col_map]
    if missing_cols:
        print(f"Adding missing columns: {missing_cols}")
        # Add to header row in sheet
        worksheet.add_cols(len(missing_cols))
        # Determine start index for new columns (1-based)
        start_col_index = len(header) + 1
        # Update header
        # gspread uses 1-based indexing for rows and cols
        # cell_list = worksheet.range(1, start_col_index, 1, start_col_index + len(missing_cols) - 1)
        # for i, cell in enumerate(cell_list):
        #     cell.value = missing_cols[i]
        # worksheet.update_cells(cell_list)
        
        # Simpler update
        worksheet.update(values=[missing_cols], range_name=gspread.utils.rowcol_to_a1(1, start_col_index))
        
        # Update local header and map
        header.extend(missing_cols)
        col_map = {name: i for i, name in enumerate(header)}

    # Indices
    idx_name = col_map.get("business_name")
    idx_zip = col_map.get("zip_code")
    idx_website = col_map.get("website")
    idx_country = col_map.get("country")
    idx_siren = col_map.get("siren")

    if idx_name is None:
        print("Error: 'business_name' column not found.")
        return

    print(f"Processing {len(rows)-1} leads...")
    
    for i, row in enumerate(rows[1:], start=2): # Start at row 2 (1-based)
        # Check if already enriched
        current_siren = row[idx_siren] if idx_siren < len(row) else ""
        if current_siren:
            continue

        name = row[idx_name] if idx_name < len(row) else ""
        if not name:
            continue

        country = row[idx_country] if idx_country < len(row) else ""
        zip_code = row[idx_zip] if idx_zip < len(row) else ""
        website = row[idx_website] if idx_website < len(row) else ""
        
        # Check if French
        is_french = country.upper() in ("FR", "FRA", "FRANCE", "")
        if not is_french and zip_code:
            # Check zip code
            clean_zip = ''.join(filter(str.isdigit, zip_code))
            if len(clean_zip) >= 2:
                dept = int(clean_zip[:2])
                if 1 <= dept <= 95 or clean_zip.startswith("97"):
                    is_french = True
        
        if not is_french:
            continue

        print(f"[{i}/{len(rows)}] Enriching: {name}")
        
        try:
            enrichment = enrich_lead(name, zip_code=zip_code, website=website)
            
            if enrichment.get("siren"):
                # Prepare updates
                updates = []
                # Order matters, matches enrichment_cols list
                vals = [
                    enrichment.get("siren", ""),
                    enrichment.get("nom_raison_sociale", ""),
                    enrichment.get("dirigeant_nom", ""),
                    enrichment.get("dirigeant_prenom", ""),
                    enrichment.get("dirigeant_qualite", ""),
                    enrichment.get("dirigeant_type", "")
                ]
                
                # We need to update specific cells
                # Find column index for 'siren'
                siren_col_idx = idx_siren + 1 # 1-based
                
                # Update the range for this row
                # We assume enrichment columns are contiguous at the end or we mapped them
                # But to be safe, let's update individual cells or a contiguous range if they are contiguous
                # In our case, if we added them, they are at the end.
                
                # Check if enrichment cols are contiguous and in order in the header
                # If they are, we can do one update
                # Otherwise update individually
                
                # Simple approach: update the cells corresponding to enrichment_cols
                # We know their indices from col_map
                
                cells_to_update = []
                for col_name, val in zip(enrichment_cols, vals):
                    col_idx = col_map[col_name] + 1
                    cells_to_update.append({
                        'range': gspread.utils.rowcol_to_a1(i, col_idx),
                        'values': [[val]]
                    })
                
                # Batch update is better
                worksheet.batch_update({'data': cells_to_update, 'value_input_option': 'RAW'})
                print(f"  -> Found SIREN: {enrichment['siren']}")
            else:
                print("  -> No match found")

        except Exception as e:
            print(f"  -> Error enriching row {i}: {e}")

        time.sleep(1.0) # Rate limit

if __name__ == "__main__":
    main()
