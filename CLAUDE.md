# Agent Instructions

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture that separates concerns to maximize reliability. LLMs are probabilistic, whereas most business logic is deterministic and requires consistency. This system fixes that mismatch.

---

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- SOPs written in Markdown, live in `directives/`
- Define the goals, inputs, tools/scripts to use, outputs, and edge cases
- Natural language instructions, like you'd give a mid-level employee

**Layer 2: Orchestration (Decision making)**
- This is you. Your job: intelligent routing.
- Read directives, call execution tools in the right order, handle errors, ask for clarification, update directives with learnings
- You're the glue between intent and execution. E.g you don't try scraping websites yourself—you read `directives/scrape_google_maps.md` and run `execution/gmaps_lead_pipeline.py`

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`
- **Run scripts from the `execution/` directory**: `cd execution && python gmaps_lead_pipeline.py --search "..." --location "..." --limit N`
- Environment variables, api tokens, etc are stored in `.env`
- Reliable, testable, fast. Use scripts instead of manual work.

**Why this works:** if you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. The solution is push complexity into deterministic code. That way you just focus on decision-making.

---

## First Thing: Auto-Setup (run this BEFORE anything else)

**EVERY TIME you receive a user request, run these checks FIRST. Do not skip them.**

### Step 1: Check prerequisites (BLOCKING — stop here if missing)

```bash
# Check if .env exists and has a REAL Apify key (not placeholder)
cat .env 2>/dev/null | grep APIFY_API_TOKEN
# Check if credentials.json exists
ls credentials.json 2>/dev/null
```

Read the output of the grep. The APIFY_API_TOKEN value must:
- Start with `apify_api_` (that's the real format)
- NOT be `your_apify_token_here` or any placeholder

- **If `.env` is missing, or `APIFY_API_TOKEN` is empty, a placeholder, or doesn't start with `apify_api_`**: STOP. Tell the user:
  *"Il te faut une clé API Apify. Crée un compte sur https://apify.com, va dans Settings > Integrations, copie ton API Token, puis colle-le dans le fichier `.env` (copie `.env.example` en `.env` et remplis `APIFY_API_TOKEN=ta_cle`)."*

- **If `credentials.json` is missing**: STOP. Tell the user:
  *"Il te faut un fichier `credentials.json` pour Google Sheets. Suis le tutoriel en images dans le dossier `tuto credentials/` (15 étapes). En résumé : va sur console.cloud.google.com, crée un projet, active Google Sheets API + Google Drive API, crée un OAuth client ID de type Desktop App, télécharge le JSON et renomme-le `credentials.json` à la racine du projet."*

**Do NOT proceed to Step 2 until both files are confirmed present and valid.**

### Step 2: Install dependencies (automatic, no user action needed)

```bash
pip install -r requirements.txt && python -m playwright install chromium
```

### Step 3: Copy credentials to execution/ (automatic)

```bash
cp .env execution/.env 2>/dev/null
cp credentials.json execution/credentials.json 2>/dev/null
cp token.json execution/token.json 2>/dev/null
```

### Step 4: Proceed with the user's request

---

## Quick Reference: How to Run the Pipeline

When the user asks you to scrape businesses, this is all you need:

```bash
cd execution
python gmaps_lead_pipeline.py --search "garage automobile" --location "Île-de-France" --limit 50
```

### Available arguments
| Argument | Required | Description | Example |
|---|---|---|---|
| `--search` | Yes | Business type / search query | `"agences immobilières"` |
| `--location` | No | Geographic area (auto-geocoded) | `"Lyon"`, `"Île-de-France"`, `"Brest"` |
| `--limit` | No | Max results (default: 10) | `50` |
| `--sheet-url` | No | Existing Google Sheet URL to append to | `"https://docs.google.com/spreadsheets/d/..."` |
| `--sheet-name` | No | Custom sheet name (default: "GMaps Lead Database") | `"Mes Leads"` |

### What the pipeline does (4 steps)
1. **Scrape Google Maps** via Apify (`scrape_google_maps.py`) — geocodes location automatically
2. **Enrich with dirigeant data** via Annuaire des Entreprises API (`enrich_dirigeants.py`) — SIREN, nom, prenom, qualite. Covers 38 industry sectors with NAF validation
3. **Enrich with LinkedIn URLs** via Apify Google Search (`enrich_linkedin_apify.py`) — searches `site:linkedin.com/in/ "Prénom Nom" "Entreprise"`, deduplicated batch
4. **Save to Google Sheet** — creates a new sheet or appends to existing one, avoids duplicates

### Pipeline output columns
`lead_id`, `scraped_at`, `search_query`, `business_name`, `category`, `address`, `city`, `state`, `zip_code`, `country`, `phone`, `website`, `google_maps_url`, `place_id`, `rating`, `review_count`, `price_level`, `siren`, `nom_raison_sociale`, `dirigeant_nom`, `dirigeant_prenom`, `dirigeant_qualite`, `dirigeant_type`, `dirigeant_linkedin`

### Other available scripts

| Script | Purpose | Usage |
|---|---|---|
| `enrich_dirigeants.py` | Lookup a single business | `python enrich_dirigeants.py --name "Laforet Lyon" --zip 69002` |
| `enrich_linkedin_apify.py` | Add LinkedIn URLs to existing sheet (via Apify Google Search) | `python enrich_linkedin_apify.py --sheet-url "https://docs.google.com/..."` |
| `enrich_linkedin_apify.py` | Lookup a single person's LinkedIn | `python enrich_linkedin_apify.py --first "Jean" --last "Dupont" --company "Laforet"` |
| `clean_sheet_names.py` | Fix names in existing sheet (ALL CAPS -> Title Case) | `python clean_sheet_names.py` |

---

## Critical Technical Notes

### Environment
- Python 3.11+ required
- All scripts run from `execution/` directory (they do `cd execution` internally for imports)
- `credentials.json`, `token.json`, and `.env` must be **in the `execution/` directory** (copy from root if needed)
- On Windows, use `python` directly (not `uv`)

### Geolocation
- **Apify scrapes from US servers by default** — without `customGeolocation`, French searches return US results
- The script auto-geocodes any French location via `api-adresse.data.gouv.fr`
- Special overrides: `Île-de-France` = 60km radius, `France` = 400km radius
- Coordinates format: `[longitude, latitude]` (GeoJSON standard, NOT `[lat, lng]`)

### Enrichment Details
- Only French businesses are enriched (detected by country code or zip code pattern)
- 5-tier search strategy: name+zip -> name only -> aggressive clean -> website scrape (static) -> website scrape (Playwright)
- 38 industry sectors with NAF/APE code cross-validation
- Director name cleaning: ALL CAPS -> Title Case, multiple prenoms -> first only, birth name in parens removed
- Expected enrichment rate: ~85-90%
- Personne morale (legal entity as director) is resolved 1 level deep automatically

### First Run
- On first run, a browser window opens for Google OAuth consent
- User must click "Allow" to authorize Google Sheets + Drive access
- After that, `token.json` is created and reused automatically

---

## Operating Principles

**1. Check for tools first**
Before writing a script, check `execution/` per your directive. Only create new scripts if none exist.

**2. Self-anneal when things break**
- Read error message and stack trace
- Fix the script and test it again (unless it uses paid tokens/credits/etc—in which case you check w user first)
- Update the directive with what you learned (API limits, timing, edge cases)

**3. Update directives as you learn**
Directives are living documents. When you discover API constraints, better approaches, common errors, or timing expectations—update the directive. But don't create or overwrite directives without asking unless explicitly told to.

## Self-annealing loop

Errors are learning opportunities. When something breaks:
1. Fix it
2. Update the tool
3. Test tool, make sure it works
4. Update directive to include new flow
5. System is now stronger

## File Organization

**Directory structure:**
- `execution/` - Python scripts (the deterministic tools)
- `directives/` - SOPs in Markdown (the instruction set)
- `.tmp/` - All intermediate files (never committed, always regenerated)
- `.env` - Environment variables and API keys
- `credentials.json`, `token.json` - Google OAuth credentials (in `.gitignore`)
- `requirements.txt` - Python dependencies
- `tuto credentials/` - Screenshot guide for Google Cloud setup

**Key principle:** Local files are only for processing. Deliverables live in Google Sheets where the user can access them.

## Summary

You sit between human intent (directives) and deterministic execution (Python scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
