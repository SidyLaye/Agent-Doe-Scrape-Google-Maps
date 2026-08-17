#!/usr/bin/env python3
"""
Enrich leads with director LinkedIn profile URLs using Apify LinkedIn Search.

Strategy:
  1. Primary: harvestapi/linkedin-profile-search-by-name (searches LinkedIn directly)
     - Uses firstName + lastName + location filter
     - No cookies needed, searches LinkedIn's own index
  2. Fallback: apify/google-search-scraper (Google site:linkedin.com/in/)
     - For any leads not found via LinkedIn native search

Only requires APIFY_API_TOKEN (no extra API key needed).

Usage:
    python enrich_linkedin_apify.py --sheet-url "https://docs.google.com/spreadsheets/d/..."
    python enrich_linkedin_apify.py --first "Jean" --last "Dupont" --company "Laforet" --city "Lyon"
"""

import os
import sys
import json
import re
import argparse
import time
from pathlib import Path
from dotenv import load_dotenv
from apify_client import ApifyClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"

LINKEDIN_SEARCH_ACTOR = "harvestapi/linkedin-profile-search-by-name"
GOOGLE_SEARCH_ACTOR = "apify/google-search-scraper"

# Known franchise/brand names -> use the brand, not the legal entity name
_BRAND_SHORTCUTS = {
    "foncia": "Foncia", "laforet": "Laforêt", "laforêt": "Laforêt",
    "orpi": "Orpi", "century 21": "Century 21", "century21": "Century 21",
    "era ": "ERA Immobilier", "guy hoquet": "Guy Hoquet",
    "stephane plaza": "Stéphane Plaza", "stéphane plaza": "Stéphane Plaza",
    "nexity": "Nexity", "bouygues": "Bouygues", "daniel feau": "Daniel Féau",
    "daniel féau": "Daniel Féau", "vaneau": "Vaneau", "solvimo": "Solvimo",
    "iad ": "IAD France", "safti": "SAFTI", "capifrance": "Capifrance",
    "square habitat": "Square Habitat", "kretz": "Kretz & Partners",
    "keller williams": "Keller Williams", "coldwell banker": "Coldwell Banker",
    "proprietes-privees": "Propriétés Privées", "l'adresse": "L'Adresse",
    "freedelion": "FREDeLION",
}


def _clean_first_name(raw: str) -> str:
    """Clean first name: ALL CAPS + multiple prénoms -> Title Case first only."""
    if not raw:
        return ""
    first = raw.strip().split()[0]
    return first.title()


def _clean_last_name(raw: str) -> str:
    """Clean last name: ALL CAPS + birth name in parens -> Title Case."""
    if not raw:
        return ""
    cleaned = re.sub(r'\s*\(.*?\)\s*', '', raw).strip()
    return cleaned.title()


def _extract_brand(company: str) -> str | None:
    """If company contains a known franchise brand, return the clean brand name."""
    if not company:
        return None
    lower = company.lower()
    for key, brand in _BRAND_SHORTCUTS.items():
        if key in lower:
            return brand
    return None


def _clean_company_for_search(company: str) -> str:
    """
    Aggressively clean company name for search queries.
    "FONCIA AGENCE CENTRALE" -> "Foncia"
    "SCCV QUARTIER SUISSE" -> "Quartier Suisse"
    """
    if not company:
        return ""

    brand = _extract_brand(company)
    if brand:
        return brand

    c = company.strip()
    c = re.sub(r'\s*\(.*?\)\s*', '', c).strip()
    c = re.sub(r'\b(s\.?a\.?s\.?|e\.?u\.?r\.?l\.?|s\.?a\.?r\.?l\.?|s\.?a\.?|'
               r's\.?c\.?i\.?|sarl|sas|eurl|sa|sci|sccv|snc|selarl)\b',
               '', c, flags=re.IGNORECASE)
    c = re.sub(r'\b(agence|agence immobiliere|agence immobilière|cabinet|groupe|'
               r'societe|société|holding|gestion|transaction|promotion|syndic)\b',
               '', c, flags=re.IGNORECASE)
    c = re.sub(r'\s+', ' ', c).strip(' -–—,.')

    if len(c) < 3:
        c = re.sub(r'\s*\(.*?\)\s*', '', company).strip()

    c = c.title()
    if len(c) > 30:
        c = c[:30].rsplit(' ', 1)[0]
    return c


# French city -> LinkedIn region mapping for scoring
_FRENCH_REGIONS = {
    "paris": "paris", "île-de-france": "paris", "ile-de-france": "paris",
    "boulogne-billancourt": "paris", "neuilly-sur-seine": "paris",
    "levallois-perret": "paris", "issy-les-moulineaux": "paris",
    "nanterre": "paris", "courbevoie": "paris", "la défense": "paris",
    "lyon": "lyon", "marseille": "marseille", "toulouse": "toulouse",
    "nice": "nice", "nantes": "nantes", "montpellier": "montpellier",
    "strasbourg": "strasbourg", "bordeaux": "bordeaux", "lille": "lille",
    "rennes": "rennes", "grenoble": "grenoble", "rouen": "rouen",
    "toulon": "toulon", "clermont-ferrand": "clermont", "nancy": "nancy",
    "metz": "metz", "tours": "tours", "dijon": "dijon", "angers": "angers",
}


# French location keywords to detect a France-based profile
_FRANCE_LOCATION_KEYWORDS = {
    "france", "paris", "lyon", "marseille", "toulouse", "nice", "nantes",
    "montpellier", "strasbourg", "bordeaux", "lille", "rennes", "grenoble",
    "rouen", "toulon", "clermont", "nancy", "metz", "tours", "dijon",
    "angers", "brest", "le mans", "amiens", "limoges", "perpignan",
    "besançon", "orléans", "caen", "mulhouse", "boulogne", "saint-",
    "île-de-france", "ile-de-france", "greater paris", "auvergne",
    "occitanie", "bretagne", "normandie", "provence", "aquitaine",
    "hauts-de-france", "grand est", "nouvelle-aquitaine", "pays de la loire",
    "centre-val de loire", "bourgogne", "corse",
}

# Expanded sector synonyms — maps a root keyword to related LinkedIn terms.
# When a Google Maps category contains any key, all synonyms become valid.
_SECTOR_SYNONYMS = {
    "immobilier": {"immobilier", "immobilière", "real estate", "agent immobilier",
                   "transaction", "gestion locative", "syndic", "copropriété",
                   "foncier", "patrimoine", "négociateur", "mandataire", "promoteur"},
    "restaurant": {"restaurant", "restauration", "restaurateur", "chef",
                   "cuisinier", "cuisine", "traiteur", "brasserie", "bistrot",
                   "food", "f&b", "hôtellerie", "gastronomie"},
    "automobile": {"automobile", "auto", "garage", "mécanique", "carrosserie",
                   "concessionnaire", "automotive", "réparation"},
    "construction": {"construction", "btp", "bâtiment", "travaux", "maçonnerie",
                     "plomberie", "électricité", "menuiserie", "rénovation"},
    "coiffeur": {"coiffeur", "coiffure", "hair", "salon", "barbier", "coloriste"},
    "beauté": {"beauté", "beauty", "esthétique", "spa", "bien-être", "onglerie"},
    "pharmacie": {"pharmacie", "pharmacien", "pharmaceutical", "officine"},
    "dentiste": {"dentiste", "dentaire", "dental", "orthodontie", "chirurgien-dentiste"},
    "médecin": {"médecin", "docteur", "medical", "health", "clinique", "santé"},
    "avocat": {"avocat", "juridique", "droit", "legal", "law", "barreau"},
    "comptable": {"comptable", "expert-comptable", "audit", "fiscal", "fiduciaire"},
    "notaire": {"notaire", "notariat", "clerc"},
    "architecte": {"architecte", "architecture", "urbanisme", "maîtrise d'œuvre"},
    "boulangerie": {"boulangerie", "boulanger", "pâtisserie", "pâtissier", "bakery"},
    "fleuriste": {"fleuriste", "floral", "flower"},
    "hôtel": {"hôtel", "hotel", "hospitality", "hébergement", "hotellerie"},
    "assurance": {"assurance", "insurance", "courtier", "actuaire"},
    "banque": {"banque", "bank", "bancaire", "finance", "crédit"},
    "informatique": {"informatique", "software", "developer", "tech", "digital", "développeur"},
    "transport": {"transport", "logistique", "logistics", "livraison", "chauffeur"},
    "nettoyage": {"nettoyage", "cleaning", "propreté", "entretien"},
    "sécurité": {"sécurité", "security", "surveillance", "gardiennage"},
    "formation": {"formation", "training", "enseignement", "éducation", "école"},
    "fitness": {"fitness", "sport", "coach", "salle de sport", "gym"},
    "optique": {"optique", "opticien", "lunettes", "optical"},
    "vétérinaire": {"vétérinaire", "veterinary", "animal", "clinique vétérinaire"},
    "pressing": {"pressing", "blanchisserie", "laundry", "teinturerie"},
    "agence de voyage": {"voyage", "travel", "tourisme", "tourism", "tour operator"},
    "imprimerie": {"imprimerie", "impression", "print", "graphisme"},
    "déménagement": {"déménagement", "moving", "déménageur"},
    "plombier": {"plombier", "plomberie", "plumbing", "chauffagiste"},
    "électricien": {"électricien", "électricité", "electrical"},
    "serrurier": {"serrurier", "serrurerie", "locksmith"},
    "photographe": {"photographe", "photographie", "photography", "photo"},
    "bijouterie": {"bijouterie", "bijoutier", "joaillerie", "jewelry"},
    "cave": {"cave", "caviste", "vin", "wine", "œnologie"},
    "librairie": {"librairie", "libraire", "bookstore"},
    "supermarché": {"supermarché", "épicerie", "grocery", "alimentation", "retail"},
}

# Stop-words to ignore when extracting keywords from category names
_CATEGORY_STOPWORDS = {
    "de", "du", "des", "le", "la", "les", "l", "un", "une", "et", "en", "à", "a",
    "au", "aux", "pour", "par", "sur", "avec", "dans", "the", "and", "of", "in",
    "for", "agency", "agence", "service", "services", "centre", "center",
}


def _get_sector_keywords(category: str) -> set:
    """
    Build sector keywords from Google Maps category — universal, covers all sectors.

    Strategy:
    1. Check if category matches any known sector synonym group -> return full synonym set
    2. Otherwise, extract meaningful words from the category itself and use them directly
    This way even "Toiletteur pour chiens" or "Cordonnerie" will generate usable keywords.
    """
    if not category:
        return set()
    cat_lower = category.lower()

    # Step 1: Check known synonym groups (word-boundary matching for short terms)
    cat_words = set(re.split(r'[\s,/\-&]+', cat_lower))  # split into words
    matched_keywords = set()
    for root, synonyms in _SECTOR_SYNONYMS.items():
        # For short keywords (<5 chars), require exact word match to avoid
        # false matches like "it" in "Italian" or "spa" in "Spain"
        if root in cat_lower:
            matched_keywords.update(synonyms)
        else:
            for s in synonyms:
                if len(s) < 5:
                    # Short: must be exact word match
                    if s in cat_words:
                        matched_keywords.update(synonyms)
                        break
                else:
                    # Long: substring is safe
                    if s in cat_lower:
                        matched_keywords.update(synonyms)
                        break

    # Step 2: Always extract raw words from the category as extra keywords
    # e.g. "Toiletteur pour chiens" -> {"toiletteur", "chiens"}
    words = re.split(r'[\s,/\-&]+', cat_lower)
    raw_keywords = {w for w in words if len(w) >= 4 and w not in _CATEGORY_STOPWORDS}

    # Also add the full category as a keyword (handles multi-word categories)
    if len(cat_lower) >= 4:
        raw_keywords.add(cat_lower)

    return matched_keywords | raw_keywords


def _is_french_location(location_text: str) -> bool:
    """Check if a LinkedIn location string indicates France."""
    loc = location_text.lower()
    return any(kw in loc for kw in _FRANCE_LOCATION_KEYWORDS)


def _score_linkedin_results(items, person: dict) -> str:
    """
    Score LinkedIn search results and return the best matching profile URL.

    STRICT scoring to avoid false positives (homonymes):
      +10: first name + last name match (required)
      +8:  company/brand found in position/headline
      +5:  location is in France
      +5:  position mentions sector-specific keywords (dynamic per category)
      +3:  location matches specific city/region
      -99: location is clearly NOT France (foreign country)

    Minimum score threshold: 16 (name + France + at least one more signal)
    """
    prenom = person.get("prenom", "").lower()
    nom = person.get("nom", "").lower()
    city = person.get("city", "").lower()
    company = person.get("company", "")
    sector = person.get("sector", "")
    clean_co = _clean_company_for_search(company).lower() if company else ""

    # Get sector-specific keywords dynamically from the Google Maps category
    sector_keywords = _get_sector_keywords(sector)

    # Map city to a broader region keyword for flexible matching
    region_key = _FRENCH_REGIONS.get(city, city)

    best_url = ""
    best_score = 0
    MIN_SCORE = 16  # name(10) + france(5) + one more signal (city/sector/company)

    candidates = list(items)  # Materialize iterator

    for item in candidates:
        url = item.get("linkedinUrl", "") or item.get("url", "")
        if not url or "linkedin.com/in/" not in url:
            continue

        score = 0
        full_name = (item.get("name", "") or "").lower()
        position = (item.get("position", "") or "").lower()

        # Name matching (required)
        if prenom in full_name and nom in full_name:
            score += 10
        else:
            continue  # Must match both first and last name exactly

        # Company matching in position/headline (strong signal)
        if clean_co and len(clean_co) >= 3 and clean_co in position:
            score += 8

        # Location analysis
        loc_data = item.get("location", {})
        location_text = ""
        if isinstance(loc_data, dict):
            location_text = loc_data.get("linkedinText", "").lower()
        elif isinstance(loc_data, str):
            location_text = loc_data.lower()

        if location_text:
            if _is_french_location(location_text):
                score += 5
                # Bonus for specific city/region match
                if city and (city in location_text or region_key in location_text):
                    score += 3
            else:
                # Non-French location is a strong negative signal
                score -= 99

        # Sector matching — dynamic keywords based on Google Maps category
        if position and sector_keywords:
            if any(kw in position for kw in sector_keywords):
                score += 5

        # Director/owner role keywords (universal — works for any sector)
        if position:
            _DIRECTOR_KEYWORDS = {
                "gérant", "gerant", "directeur", "directrice", "fondateur",
                "fondatrice", "président", "presidente", "pdg", "ceo",
                "owner", "propriétaire", "proprietaire", "co-fondateur",
                "associé", "associee", "managing", "dirigeant", "dirigeante",
            }
            if any(kw in position for kw in _DIRECTOR_KEYWORDS):
                score += 3

        if score >= MIN_SCORE and score > best_score:
            best_score = score
            best_url = url.split("?")[0]

    return best_url


# ---------------------------------------------------------------------------
# LinkedIn Native Search (Primary method)
# ---------------------------------------------------------------------------

def _search_linkedin_native(client: ApifyClient, person: dict) -> str:
    """
    Search LinkedIn directly for a person using harvestapi/linkedin-profile-search-by-name.

    Args:
        client: ApifyClient instance
        person: dict with keys: prenom, nom, city, company

    Returns:
        LinkedIn profile URL or empty string
    """
    prenom = person.get("prenom", "")
    nom = person.get("nom", "")
    city = person.get("city", "")

    if not prenom or not nom:
        return ""

    # Don't use locations filter — LinkedIn locations are region-level
    # ("Greater Paris Metropolitan Region") not city-level, so filtering
    # by city name drops valid results. Instead, score by location proximity.
    run_input = {
        "firstName": prenom,
        "lastName": nom,
        "profileScraperMode": "Short",
        "maxItems": 10,
    }

    try:
        run = client.actor(LINKEDIN_SEARCH_ACTOR).call(
            run_input=run_input,
            timeout_secs=60,
        )
    except Exception as e:
        print(f"    LinkedIn search error for {prenom} {nom}: {e}")
        return ""

    if not run:
        return ""

    return _score_linkedin_results(
        client.dataset(run["defaultDatasetId"]).iterate_items(),
        person,
    )


def _search_linkedin_native_batch(client: ApifyClient,
                                   persons: list[dict]) -> dict[str, str]:
    """
    Search LinkedIn for multiple persons using parallel actor runs.

    Args:
        client: ApifyClient instance
        persons: list of dicts with keys: key, prenom, nom, city, company

    Returns:
        {key: linkedin_url}
    """
    if not persons:
        return {}

    # Start all runs in parallel (non-blocking) — NO location filter
    pending_runs = []  # list of (key, person, run)
    for person in persons:
        prenom = person.get("prenom", "")
        nom = person.get("nom", "")
        key = person.get("key", "")

        if not prenom or not nom:
            continue

        run_input = {
            "firstName": prenom,
            "lastName": nom,
            "profileScraperMode": "Short",
            "maxItems": 10,
        }

        try:
            run = client.actor(LINKEDIN_SEARCH_ACTOR).start(run_input=run_input)
            if run:
                pending_runs.append((key, person, run))
                city = person.get("city", "")
                print(f"    Started search: {prenom} {nom}" + (f" ({city})" if city else ""), flush=True)
        except Exception as e:
            print(f"    Error starting search for {prenom} {nom}: {e}", flush=True)

    if not pending_runs:
        return {}

    # Wait for all runs to complete and collect results
    results = {}
    print(f"\n  Waiting for {len(pending_runs)} LinkedIn searches to complete...", flush=True)

    for key, person, run in pending_runs:
        run_id = run.get("id", "")
        prenom = person.get("prenom", "")
        nom = person.get("nom", "")

        try:
            client.run(run_id).wait_for_finish(wait_secs=120)

            run_info = client.run(run_id).get()
            if not run_info:
                continue

            dataset_id = run_info.get("defaultDatasetId", "")
            if not dataset_id:
                continue

            best_url = _score_linkedin_results(
                client.dataset(dataset_id).iterate_items(),
                person,
            )

            if best_url:
                results[key] = best_url
                print(f"    {prenom} {nom} -> {best_url}", flush=True)
            else:
                print(f"    {prenom} {nom} -> not found", flush=True)

        except Exception as e:
            print(f"    Error collecting results for {prenom} {nom}: {e}", flush=True)

    return results


# ---------------------------------------------------------------------------
# Google Search Fallback
# ---------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    """Remove accents: Stéphane -> Stephane, Cédric -> Cedric."""
    import unicodedata
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )


def build_linkedin_query(prenom: str, nom: str, company: str) -> str:
    """Build a Google search query for LinkedIn (precise, with company)."""
    clean_p = _clean_first_name(prenom)
    clean_n = _clean_last_name(nom)
    clean_c = _clean_company_for_search(company)

    if not clean_p or not clean_n:
        return ""

    query = f'site:linkedin.com/in/ "{clean_p} {clean_n}"'
    if clean_c and len(clean_c) >= 3:
        query += f' "{clean_c}"'
    return query


def build_linkedin_query_broad(prenom: str, nom: str, city: str = "",
                                sector: str = "") -> str:
    """Build a broader Google search query (with city/sector, no company)."""
    clean_p = _clean_first_name(prenom)
    clean_n = _clean_last_name(nom)

    if not clean_p or not clean_n:
        return ""

    query = f'site:linkedin.com/in/ "{clean_p} {clean_n}"'
    if city:
        query += f' {city}'
    if sector:
        query += f' {sector}'
    return query


def _build_linkedin_query_nameonly(prenom: str, nom: str) -> str:
    """Build ultra-broad query: name only, no company/city."""
    clean_p = _clean_first_name(prenom)
    clean_n = _clean_last_name(nom)
    if not clean_p or not clean_n:
        return ""
    return f'site:linkedin.com/in/ "{clean_p} {clean_n}"'


def _build_linkedin_query_noaccent(prenom: str, nom: str, company: str) -> str:
    """Build query with accents stripped (catches LinkedIn profiles without accents)."""
    clean_p = _strip_accents(_clean_first_name(prenom))
    clean_n = _strip_accents(_clean_last_name(nom))
    clean_c = _clean_company_for_search(company)
    if not clean_p or not clean_n:
        return ""
    query = f'site:linkedin.com/in/ "{clean_p} {clean_n}"'
    if clean_c and len(clean_c) >= 3:
        query += f' "{clean_c}"'
    return query


def _is_foreign_linkedin_url(url: str) -> bool:
    """Check if a LinkedIn URL subdomain indicates a non-French profile.

    LinkedIn uses country subdomains: fr.linkedin.com (France),
    na.linkedin.com (North America), cl.linkedin.com (Chile), etc.
    """
    # Extract subdomain from URL
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    parts = host.split(".")
    if len(parts) <= 2:
        return False  # bare linkedin.com — no country signal
    subdomain = parts[0].lower()
    # Accept French and neutral subdomains
    if subdomain in ("fr", "www", "linkedin"):
        return False
    # Reject known non-French country subdomains
    non_french_subdomains = {
        "na", "us", "uk", "de", "es", "it", "br", "au", "ca", "mx",
        "at", "ch", "nl", "pt", "jp", "cn", "ar", "co", "pe", "za",
        "cl", "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "bg",
        "hr", "sk", "ie", "nz", "sg", "hk", "tw", "kr", "th", "id",
        "my", "ph", "vn", "eg", "ng", "ke", "gh", "tz", "tr", "il",
        "ae", "sa", "qa", "kw", "bh", "om", "pk", "bd", "lk", "mm",
        "ru", "ua", "by", "kz", "uz", "ge", "am", "az",
    }
    if subdomain in non_french_subdomains:
        return True
    return False


def _extract_linkedin_url(organic_results: list, person: dict = None) -> str:
    """
    Extract the best LinkedIn profile URL from Google organic results.

    If person dict is provided, validate against location/sector to reject
    obvious homonymes (foreign profiles, wrong sector) and wrong-person matches.
    """
    nom = _strip_accents(person.get("nom", "")).lower().replace(" ", "-") if person else ""
    prenom = _strip_accents(person.get("prenom", "")).lower() if person else ""

    for r in organic_results:
        url = r.get("url", "") or r.get("link", "")
        if "linkedin.com/in/" not in url:
            continue

        # If no person info for validation, accept first match
        if not person:
            return url.split("?")[0]

        # CRITICAL: Check that the URL slug contains the person's last name
        # e.g. linkedin.com/in/pascal-delaval-63345b8b should contain "delaval"
        url_slug = url.split("/in/")[-1].split("?")[0].lower()
        url_slug_clean = _strip_accents(url_slug)
        if nom and nom not in url_slug_clean:
            continue  # URL doesn't match the person's name at all

        # Check LinkedIn URL subdomain for country (very reliable signal)
        if _is_foreign_linkedin_url(url):
            continue

        # Validate using Google snippet (title + description)
        snippet = (r.get("title", "") + " " + r.get("description", "")).lower()

        # Check for non-French indicators in snippet
        non_french_indicators = {
            "united states", "usa", "uk ", "united kingdom", "germany",
            "deutschland", "españa", "spain", "italia", "italy", "canada",
            "australia", "india", "brasil", "brazil", "austria", "schweiz",
            "switzerland", "nederland", "belgium", "portugal", "china",
            "japan", "mexico", "illinois", "california", "texas", "new york",
            "florida", "ohio", "michigan", "pennsylvania", "georgia",
        }
        if any(ind in snippet for ind in non_french_indicators):
            continue  # Skip foreign profiles

        return url.split("?")[0]
    return ""


def _run_google_search(client: ApifyClient, queries: list[str],
                       query_person_map: dict = None) -> dict[str, str]:
    """Run a batch of Google searches via Apify. Returns {query: linkedin_url}.

    Args:
        query_person_map: optional {query: person_dict} for validation of results
    """
    if not queries:
        return {}

    run_input = {
        "queries": "\n".join(queries),
        "maxPagesPerQuery": 1,
        "countryCode": "fr",
        "languageCode": "fr",
        "mobileResults": False,
        "saveHtml": False,
    }

    try:
        run = client.actor(GOOGLE_SEARCH_ACTOR).call(run_input=run_input)
    except Exception as e:
        print(f"  Google Search error: {e}")
        return {}

    if not run:
        return {}

    results = {}
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        search_query = ""
        sq = item.get("searchQuery", {})
        if isinstance(sq, dict):
            search_query = sq.get("term", "") or sq.get("query", "")
        elif isinstance(sq, str):
            search_query = sq

        organic = item.get("organicResults", [])
        person = (query_person_map or {}).get(search_query)
        linkedin_url = _extract_linkedin_url(organic, person=person)
        if search_query:
            results[search_query] = linkedin_url

    return results


# ---------------------------------------------------------------------------
# Main batch search: LinkedIn native + Google fallback
# ---------------------------------------------------------------------------

def search_linkedin_batch(queries_with_keys: dict[str, list],
                          broad_info: dict = None) -> dict[str, str]:
    """
    Multi-strategy LinkedIn search:
      1. LinkedIn native search (harvestapi/linkedin-profile-search-by-name)
      2. Google Search fallback for remaining leads

    Args:
        queries_with_keys: {query_string: [list of lead_keys]}
            (query_string is used as the key for results)
        broad_info: {query_string: {"prenom": ..., "nom": ..., "city": ...,
                     "sector": ..., "company": ...}}

    Returns:
        {query_string: linkedin_url}
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("Error: APIFY_API_TOKEN not found in .env")
        return {}

    all_queries = list(queries_with_keys.keys())
    if not all_queries:
        return {}

    client = ApifyClient(api_token)
    final_results = {}

    # ---- STEP 1: LinkedIn Native Search (parallel) ----
    print(f"\n  Step 1 - LinkedIn native search: {len(all_queries)} persons...", flush=True)

    persons = []
    for query in all_queries:
        info = (broad_info or {}).get(query, {})
        if not info:
            continue
        persons.append({
            "key": query,
            "prenom": info.get("prenom", ""),
            "nom": info.get("nom", ""),
            "city": info.get("city", ""),
            "company": info.get("company", ""),
        })

    if persons:
        native_results = _search_linkedin_native_batch(client, persons)
        final_results.update(native_results)

    found_native = len(final_results)
    print(f"\n  LinkedIn native: {found_native}/{len(all_queries)} found", flush=True)

    # ---- STEP 2: Google Search fallback (4 passes, progressively broader) ----
    failed_queries = [q for q in all_queries if not final_results.get(q)]

    if failed_queries and broad_info:
        print(f"\n  Step 2 - Google Search fallback: {len(failed_queries)} remaining...", flush=True)

        # Pass A: Precise — "Prénom Nom" "Company"
        a_person_map = {q: broad_info.get(q, {}) for q in failed_queries}
        google_results_a = _run_google_search(client, failed_queries,
                                               query_person_map=a_person_map)
        for q in failed_queries:
            url = google_results_a.get(q, "")
            if url:
                final_results[q] = url
        found_a = sum(1 for q in failed_queries if final_results.get(q))
        print(f"  Google pass A (precise+company): {found_a}/{len(failed_queries)} found", flush=True)

        # Pass B: Broad — "Prénom Nom" city sector (no company)
        still_missing = [q for q in failed_queries if not final_results.get(q)]
        if still_missing:
            broad_queries = {}  # broad_query -> original_query
            for orig_q in still_missing:
                info = broad_info.get(orig_q, {})
                if not info:
                    continue
                broad_q = build_linkedin_query_broad(
                    info.get("prenom", ""),
                    info.get("nom", ""),
                    city=info.get("city", ""),
                    sector=info.get("sector", ""),
                )
                if broad_q and broad_q != orig_q:
                    broad_queries[broad_q] = orig_q

            if broad_queries:
                print(f"  Google pass B (city+sector): {len(broad_queries)} queries...", flush=True)
                b_person_map = {}
                for broad_q, orig_q in broad_queries.items():
                    b_person_map[broad_q] = broad_info.get(orig_q, {})
                google_results_b = _run_google_search(
                    client, list(broad_queries.keys()),
                    query_person_map=b_person_map,
                )
                found_b = 0
                for broad_q, orig_q in broad_queries.items():
                    url = google_results_b.get(broad_q, "")
                    if url:
                        final_results[orig_q] = url
                        found_b += 1
                print(f"  Google pass B: {found_b}/{len(broad_queries)} found", flush=True)

        # Pass C: Ultra-broad — "Prénom Nom" alone (no company, no city)
        still_missing = [q for q in failed_queries if not final_results.get(q)]
        if still_missing:
            name_queries = {}  # name_query -> original_query
            for orig_q in still_missing:
                info = broad_info.get(orig_q, {})
                if not info:
                    continue
                name_q = _build_linkedin_query_nameonly(
                    info.get("prenom", ""),
                    info.get("nom", ""),
                )
                if name_q and name_q != orig_q and name_q not in name_queries:
                    name_queries[name_q] = orig_q

            if name_queries:
                print(f"  Google pass C (name only): {len(name_queries)} queries...", flush=True)
                # Build person map for validation (name-only queries are high homonyme risk)
                c_person_map = {}
                for name_q, orig_q in name_queries.items():
                    c_person_map[name_q] = broad_info.get(orig_q, {})
                google_results_c = _run_google_search(
                    client, list(name_queries.keys()),
                    query_person_map=c_person_map,
                )
                found_c = 0
                for name_q, orig_q in name_queries.items():
                    url = google_results_c.get(name_q, "")
                    if url:
                        final_results[orig_q] = url
                        found_c += 1
                print(f"  Google pass C: {found_c}/{len(name_queries)} found", flush=True)

        # Pass D: No-accent — strip accents from names (Stéphane -> Stephane)
        still_missing = [q for q in failed_queries if not final_results.get(q)]
        if still_missing:
            noaccent_queries = {}
            for orig_q in still_missing:
                info = broad_info.get(orig_q, {})
                if not info:
                    continue
                na_q = _build_linkedin_query_noaccent(
                    info.get("prenom", ""),
                    info.get("nom", ""),
                    info.get("company", ""),
                )
                if na_q and na_q != orig_q and na_q not in noaccent_queries:
                    noaccent_queries[na_q] = orig_q

            if noaccent_queries:
                print(f"  Google pass D (no accents): {len(noaccent_queries)} queries...", flush=True)
                d_person_map = {}
                for na_q, orig_q in noaccent_queries.items():
                    d_person_map[na_q] = broad_info.get(orig_q, {})
                google_results_d = _run_google_search(
                    client, list(noaccent_queries.keys()),
                    query_person_map=d_person_map,
                )
                found_d = 0
                for na_q, orig_q in noaccent_queries.items():
                    url = google_results_d.get(na_q, "")
                    if url:
                        final_results[orig_q] = url
                        found_d += 1
                print(f"  Google pass D: {found_d}/{len(noaccent_queries)} found", flush=True)

    # ---- Summary ----
    total_found = sum(1 for v in final_results.values() if v)
    print(f"\n  TOTAL LinkedIn profiles found: {total_found}/{len(all_queries)}", flush=True)

    for q in all_queries:
        url = final_results.get(q, "")
        info = (broad_info or {}).get(q, {})
        name = f"{info.get('prenom', '')} {info.get('nom', '')}" if info else q
        status = url if url else "not found"
        if len(name) > 30:
            name = name[:30] + "..."
        print(f"    {name} -> {status}", flush=True)

    return final_results


def search_single(prenom: str, nom: str, company: str = "",
                   city: str = "") -> str:
    """Search LinkedIn for a single person. Returns URL or empty string."""
    query = build_linkedin_query(prenom, nom, company)
    if not query:
        return ""

    broad_info = {query: {
        "prenom": prenom, "nom": nom,
        "city": city, "sector": "",
        "company": company,
    }}
    results = search_linkedin_batch({query: ["single"]}, broad_info=broad_info)
    return results.get(query, "")


def enrich_sheet_linkedin(sheet_url: str):
    """
    Add LinkedIn URLs to an existing Google Sheet.
    Reads leads with dirigeant data but no LinkedIn URL,
    searches via LinkedIn native + Google fallback, and writes results back.
    """
    import gspread
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", SECRETS_DIR / "token.json"))
    if token_file.exists():
        try:
            with token_file.open('r', encoding='utf-8') as token:
                token_data = json.load(token)
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
                creds = Credentials.from_authorized_user_info(token_data, scopes)
        except Exception as e:
            print(f"Error loading token: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(SECRETS_DIR / "credentials.json")))
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ])
            creds = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with token_file.open('w', encoding='utf-8') as token:
            token.write(creds.to_json())

    gc = gspread.authorize(creds)

    if '/d/' in sheet_url:
        sheet_id = sheet_url.split('/d/')[1].split('/')[0]
    else:
        sheet_id = sheet_url
    spreadsheet = gc.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    rows = worksheet.get_all_values()
    if not rows:
        print("Sheet is empty.")
        return

    header = rows[0]
    col_map = {name: i for i, name in enumerate(header)}

    required = ["dirigeant_prenom", "dirigeant_nom"]
    for col in required:
        if col not in col_map:
            print(f"Error: column '{col}' not found in sheet.")
            return

    if "dirigeant_linkedin" not in col_map:
        new_col_idx = len(header)
        col_map["dirigeant_linkedin"] = new_col_idx
        header.append("dirigeant_linkedin")
        worksheet.update_cell(1, new_col_idx + 1, "dirigeant_linkedin")
        print("Added 'dirigeant_linkedin' column to sheet")

    linkedin_col_idx = col_map["dirigeant_linkedin"]

    leads_to_enrich = []
    queries_map = {}
    broad_info = {}

    for i, row in enumerate(rows[1:], start=2):
        def get_val(col_name):
            idx = col_map.get(col_name)
            if idx is not None and idx < len(row):
                return row[idx].strip()
            return ""

        prenom = get_val("dirigeant_prenom")
        nom = get_val("dirigeant_nom")
        linkedin = get_val("dirigeant_linkedin")
        dirigeant_type = get_val("dirigeant_type")

        if linkedin or not prenom or not nom:
            continue
        if "morale" in dirigeant_type.lower():
            continue

        company = get_val("nom_raison_sociale") or get_val("business_name")
        city = get_val("city")
        category = get_val("category")
        query = build_linkedin_query(prenom, nom, company)
        if not query:
            continue

        leads_to_enrich.append((i, query))
        if query not in queries_map:
            queries_map[query] = []
        queries_map[query].append(i)
        broad_info[query] = {
            "prenom": prenom, "nom": nom,
            "city": city, "sector": category,
            "company": company,
        }

    print(f"Found {len(leads_to_enrich)} leads to enrich ({len(queries_map)} unique queries)")

    if not leads_to_enrich:
        print("Nothing to enrich.")
        return

    search_results = search_linkedin_batch(queries_map, broad_info=broad_info)

    updates = []
    found_count = 0
    for row_num, query in leads_to_enrich:
        linkedin_url = search_results.get(query, "")
        if linkedin_url:
            cell = gspread.utils.rowcol_to_a1(row_num, linkedin_col_idx + 1)
            updates.append({
                'range': cell,
                'values': [[linkedin_url]]
            })
            found_count += 1

    if updates:
        chunk_size = 50
        for j in range(0, len(updates), chunk_size):
            chunk = updates[j:j + chunk_size]
            worksheet.batch_update(chunk)
            if j + chunk_size < len(updates):
                time.sleep(1)

        print(f"\nUpdated {found_count}/{len(leads_to_enrich)} leads with LinkedIn URLs")
    else:
        print("\nNo LinkedIn URLs found for any lead")

    print(f"Sheet: {spreadsheet.url}")


def main():
    parser = argparse.ArgumentParser(
        description="Enrich leads with LinkedIn URLs (LinkedIn native + Google fallback)"
    )
    parser.add_argument("--sheet-url", help="Google Sheet URL to enrich")
    parser.add_argument("--first", help="Single lookup: director first name")
    parser.add_argument("--last", help="Single lookup: director last name")
    parser.add_argument("--company", help="Single lookup: company name")
    parser.add_argument("--city", help="Single lookup: city for location filter")

    args = parser.parse_args()

    if not os.getenv("APIFY_API_TOKEN"):
        print("Error: APIFY_API_TOKEN not found in .env")
        sys.exit(1)

    if args.sheet_url:
        enrich_sheet_linkedin(args.sheet_url)
    elif args.first and args.last:
        company = args.company or ""
        city = args.city or ""
        url = search_single(args.first, args.last, company, city)
        print(json.dumps({"dirigeant_linkedin": url}, indent=2, ensure_ascii=False))
    else:
        parser.print_help()
        print("\nExamples:")
        print('  python enrich_linkedin_apify.py --sheet-url "https://docs.google.com/spreadsheets/d/..."')
        print('  python enrich_linkedin_apify.py --first "Jean" --last "Dupont" --company "Laforet" --city "Lyon"')


if __name__ == "__main__":
    main()
