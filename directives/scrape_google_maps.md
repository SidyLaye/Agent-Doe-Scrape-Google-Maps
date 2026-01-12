# Directive: Scrape Google Maps Businesses

## 1. Overview
This directive provides a standardized procedure for searching and extracting business listings from Google Maps using Apify. It focuses on gathering raw business data (title, address, website, phone, category, ratings) which can later be used for lead enrichment.

## 2. When to Use
Use this directive when you need to:
- Identify businesses in a specific industry or niche.
- Target businesses within a particular geographic location.
- Build the initial list of prospects before running enrichment workflows.

## 3. Inputs
- `search_query`: The industry or business type to search for (e.g., "Digital Marketing Agency").
- `location` (optional): The geographical area to focus the search (ex: "Paris, France").
- `limit`: The maximum number of results to fetch (default: 10).
- `APIFY_API_TOKEN`: Required in `.env` to authenticate with Apify.

## 4. Execution

### Step 1: Pre-execution Check
Verify that:
- `.env` contains a valid `APIFY_API_TOKEN`.
- `credentials.json` is present at the project root.

### Step 2: Run the GMaps to GSheet Pipeline
Run the following command from the project root using `uv`:

```bash
uv run execution/gmaps_lead_pipeline.py \
    --search "{search_query}" \
    --location "{location}" \
    --limit {limit}
```

*Replace `{search_query}`, `{location}`, and `{limit}` with the actual parameters.*

### Step 3: Verify Output
- **Terminal**: The script will show "Created new sheet" or "Opened existing sheet" and the number of leads added.
- **Google Sheets**: Open your Google Drive and look for a file named "GMaps Lead Database" (or the name you specified).

## 5. Enrichment: Dirigeant Data (French Businesses)

After scraping, the pipeline automatically enriches French businesses with director data using the free [Annuaire des Entreprises API](https://recherche-entreprises.api.gouv.fr).

### How it works
1. For each lead with a French country code (FR), the pipeline searches the API by `business_name` + optional `zip_code`.
2. If the director is a legal entity (personne morale), it resolves the SIREN of that entity to find the physical person behind it.
3. Auditors (commissaires aux comptes) are filtered out — only actual directors are kept.

### Added columns
| Column | Description |
|---|---|
| `siren` | SIREN number of the matched company |
| `nom_raison_sociale` | Official legal name from the register |
| `dirigeant_nom` | Director's last name |
| `dirigeant_prenom` | Director's first name |
| `dirigeant_qualite` | Director's role (e.g., Président, Gérant) |
| `dirigeant_type` | `personne physique` or `personne morale` |

### Standalone usage
You can also enrich a single business name without running the full pipeline:
```bash
uv run execution/enrich_dirigeants.py --name "Laforet Lyon" --zip 69002
```

### Enrichment strategy (5-tier)
1. **Name search + zip** — Search the government API with cleaned business name variants + zip code filter
2. **Name search (no zip)** — If zip-filtered search fails, retry without zip code to catch name mismatches
3. **Aggressive name clean** — Strip legal forms (SAS, EURL…), per-industry noise words and brand names (e.g., auto brands for garages, franchise names for real estate agencies). Brand/noise stripping is industry-aware: only relevant words are removed based on the Google Maps category. Searches with and without zip
4. **Website scrape (fast)** — Scrape SIREN/SIRET from the company website using static HTTP (mentions-legales, CGU pages)
5. **Website scrape (Playwright)** — If static scrape fails, use headless Chromium to render JS-heavy sites and extract SIREN

All results are **scored** with:
- Active company bonus, name-word overlap, exact containment, dirigeant presence
- **Department validation**: checks both siege AND matching_etablissements. Companies with a branch in the target département get a bonus (+8); companies with NO presence are penalized (-30)
- **NAF/APE activity validation (all sectors)**: the Google Maps category is matched against a keyword-based industry detector covering **38 sectors** (auto, restaurant, immobilier, beauté, BTP, informatique, santé, pharmacie, optique, vétérinaire, fitness, éducation, formation, comptabilité, juridique, assurance, banque, transport, logistique, nettoyage, sécurité, hôtellerie, tourisme, commerce de détail, commerce de gros, textile, agriculture, industrie, énergie, télécom, média, culture, sport, déménagement, funéraire, jardinerie, animalerie, pressing). When the category matches a known industry, results with a matching NAF get +10 bonus; results with a conflicting NAF get -50 penalty. Categories that don't match any known industry skip NAF validation (safe default)
- **Weak identity guard**: if aggressive cleaning leaves only city names/directions, the match is rejected
- **Tier fallthrough**: if Tier 1 (with zip) finds only low-scoring results (<15), Tier 2 (without zip) is automatically tried

Expected enrichment rate: **~85-90%** for French businesses (up from ~60% before improvements).

Requires `playwright` and Chromium: `pip install playwright && python -m playwright install chromium`

### Known limitations
- **Name matching**: Google Maps uses commercial names (e.g., "Laforêt Lyon 2Ème") while the register uses legal names (e.g., "LAFORET FRANCHISE"). The multi-tier search + aggressive cleaning handles most cases, but ~5-10% may still fail for very generic names (e.g., "Auto Moto", "abcd") or franchise locations whose legal entity has no resemblance to the brand.
- **SAS holding structures**: Many companies have a holding company as director. The script resolves one level deep automatically.
- **French only**: Non-French businesses are skipped (also detects French zip codes even if country is wrong).
- **SPA sites without SIREN**: Some sites don't display their SIREN anywhere (even after JS rendering). These remain unresolved.
- **Rate limiting**: The script adds small delays between API calls. For large batches (100+ leads), expect ~2-5 minutes of enrichment time (longer with Playwright fallbacks).
- **False positives on generic names**: Names like "Hertz Location Camping-Car Paris Sud-Est" may match unrelated businesses because the aggressive clean leaves only "Paris". The weak-identity guard + NAF validation catches most of these. The pipeline passes `gmaps_category` to the enrichment, and the industry detector cross-validates NAF codes across all 38 supported sectors (e.g., a "Concessionnaire automobile" won't match a coiffure salon NAF 96.02A, a "Restaurant" won't match an auto dealer NAF 45.11Z). Brand stripping is per-industry: auto brands (Renault, BMW) only stripped for automotive, franchise names (Century 21, Laforêt) only for real estate, etc.
- **Etablissement-level department check**: A company's siege may be in a different department, but it can have branches (etablissements) elsewhere. The scoring now checks `matching_etablissements` from the API to properly validate geographic presence.

## 6. Geolocation (automatic, covers all of France)

The Apify actor runs from US-based servers by default. Without explicit geolocation, searches for French businesses will return mixed US + French results.

The script **automatically geocodes any location** using the free French government API (`api-adresse.data.gouv.fr`). No configuration needed — just pass `--location "Brest"` or `--location "Clermont-Ferrand"` and it works.

### How it works
1. **Special overrides** are checked first: `Île-de-France` (60km radius), `France` (400km)
2. For everything else, the location name is sent to `api-adresse.data.gouv.fr/search/` which returns exact coordinates
3. Radius is set based on result type: `municipality` = 15km, `locality` = 10km, `street/housenumber` = 5km
4. If geocoding fails (e.g., foreign location), falls back to France-wide (400km)

### Adding new special overrides
To add region-level overrides (larger radius), edit `_SPECIAL_LOCATIONS` in `scrape_google_maps.py`. Format: `{"coordinates": [lng, lat], "radiusKm": N}`.

**Important**: Coordinates are `[longitude, latitude]` (GeoJSON standard), not `[lat, lng]`.

## 7. Quality Standards
- **Duplicates**: The script automatically avoids adding the same business twice to the same sheet (based on name and address).
- **Location Context**: Use the `--location` parameter if you want to force results in a specific area.

## 8. Working Directory Note
When running via `python execution/gmaps_lead_pipeline.py` (from the `execution/` directory), `credentials.json` and `token.json` must be present in that directory. When running via `uv run execution/gmaps_lead_pipeline.py` (from project root), they should be at the project root.
