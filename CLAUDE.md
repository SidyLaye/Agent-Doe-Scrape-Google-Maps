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
- You're the glue between intent and execution. E.g you don't try scraping websites yourself—you read `directives/scrape_google_maps.md` and run `backend/execution/gmaps_lead_pipeline.py`

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `backend/execution/`
- **Run scripts from the `backend/execution/` directory**: `cd backend/execution && python gmaps_lead_pipeline.py --search "..." --location "..." --limit N`
- Environment variables and API tokens are stored only in `backend/.env`; OAuth files are stored in `backend/secrets/`.
- Reliable, testable, fast. Use scripts instead of manual work.

**Why this works:** if you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. The solution is push complexity into deterministic code. That way you just focus on decision-making.

---

## First Thing: Auto-Setup (run this BEFORE anything else)

**EVERY TIME you receive a user request, run these checks FIRST. Do not skip them.**

### Step 1: Check prerequisites (BLOCKING — stop here if missing)

```bash
# Check if .env exists and has a REAL Apify key (not placeholder)
cat backend/.env 2>/dev/null | grep APIFY_API_TOKEN
# Check if credentials.json exists
ls backend/secrets/credentials.json 2>/dev/null
```

Read the output of the grep. The APIFY_API_TOKEN value must:
- Start with `apify_api_` (that's the real format)
- NOT be `your_apify_token_here` or any placeholder

- **If `backend/.env` is missing, or `APIFY_API_TOKEN` is empty, a placeholder, or doesn't start with `apify_api_`**: STOP. Tell the user:
  *"Il te faut une clé API Apify. Crée un compte sur https://apify.com, va dans Settings > Integrations, copie ton API Token, puis colle-le dans le fichier `backend/.env` (copie `backend/.env.example` en `backend/.env` et remplis `APIFY_API_TOKEN=ta_cle`)."*

- **If `backend/secrets/credentials.json` is missing**: STOP. Tell the user:
  *"Il te faut un fichier `credentials.json` pour Google Sheets. Suis le tutoriel en images dans le dossier `tuto credentials/` (15 étapes), puis place le JSON dans `backend/secrets/credentials.json`."*

**Do NOT proceed to Step 2 until both files are confirmed present and valid.**

### Step 2: Install dependencies (automatic, no user action needed)

```bash
pip install -r backend/requirements.txt && python -m playwright install chromium
```

### Step 3: Credentials layout

Do not copy secrets. The backend and execution scripts load `backend/.env` and `backend/secrets/` directly.

### Step 4: Proceed with the user's request

---

## Quick Reference: How to Run the Pipeline

When the user asks you to scrape businesses, this is all you need:

```bash
cd backend/execution
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

### What the pipeline does (3 steps)
1. **Scrape Google Maps** via Apify (`scrape_google_maps.py`) — geocodes location automatically
2. **Enrich with dirigeant data** via Annuaire des Entreprises API (`enrich_dirigeants.py`) — SIREN, nom, prenom, qualite. Covers 38 industry sectors with NAF validation
3. **Save to Google Sheet** — creates a new sheet or appends to existing one, avoids duplicates

### Pipeline output columns
`lead_id`, `scraped_at`, `search_query`, `business_name`, `category`, `address`, `city`, `state`, `zip_code`, `country`, `phone`, `website`, `google_maps_url`, `place_id`, `rating`, `review_count`, `price_level`, `siren`, `nom_raison_sociale`, `dirigeant_nom`, `dirigeant_prenom`, `dirigeant_qualite`, `dirigeant_type`

### Other available scripts

| Script | Purpose | Usage |
|---|---|---|
| `enrich_dirigeants.py` | Lookup a single business | `python enrich_dirigeants.py --name "Laforet Lyon" --zip 69002` |
| `clean_sheet_names.py` | Fix names in existing sheet (ALL CAPS -> Title Case) | `python clean_sheet_names.py` |

---

## Critical Technical Notes

### Environment
- Python 3.11+ required
- All scripts run from `backend/execution/`.
- Secrets remain in `backend/.env` and `backend/secrets/`; never duplicate them in the execution directory.
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
- After that, `backend/secrets/token.json` is created and reused automatically

---

## Operating Principles

**1. Check for tools first**
Before writing a script, check `backend/execution/` per your directive. Only create new scripts if none exist.

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
- `backend/execution/` - Python scripts (the deterministic tools)
- `directives/` - SOPs in Markdown (the instruction set)
- `.tmp/` - All intermediate files (never committed, always regenerated)
- `backend/.env` - Environment variables and API keys
- `backend/secrets/credentials.json`, `backend/secrets/token.json` - Google OAuth credentials (in `.gitignore`)
- `backend/requirements.txt` - Backend and execution dependencies
- `tuto credentials/` - Screenshot guide for Google Cloud setup

**Key principle:** Local files are only for processing. Deliverables live in Google Sheets where the user can access them.

## Summary

You sit between human intent (directives) and deterministic execution (Python scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.

