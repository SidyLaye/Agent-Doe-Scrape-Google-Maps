"""Find public decision-maker profiles for companies using Google/LinkedIn results."""

import os
import re
from urllib.parse import urlsplit, urlunsplit

from apify_client import ApifyClient


GOOGLE_SEARCH_ACTOR = "apify/google-search-scraper"
ROLE_PATTERN = re.compile(
    r"\b(ceo|chief executive officer|directeur(?:rice)?(?: général(?:e)?)?|"
    r"directeur(?:rice)? commercial(?:e)?|directeur(?:rice)? marketing|"
    r"fondateur|fondatrice|co[- ]?fondateur|co[- ]?fondatrice|founder|owner|propriétaire|"
    r"gérant(?:e)?|manager|managing director|responsable commercial(?:e)?)\b",
    re.IGNORECASE,
)


def _dataset_id(run) -> str:
    value = getattr(run, "default_dataset_id", "")
    if value:
        return value
    if isinstance(run, dict):
        return run.get("defaultDatasetId", "") or run.get("default_dataset_id", "")
    return ""


def _clean_linkedin_url(url: str) -> str:
    if not url or "linkedin.com/in/" not in url.lower():
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/"), "", ""))


def _parse_result(result: dict, company: str) -> dict | None:
    url = _clean_linkedin_url(result.get("url", ""))
    title = (result.get("title") or "").strip()
    description = (result.get("description") or "").strip()
    combined = f"{title} {description}"
    role_match = ROLE_PATTERN.search(combined)
    if not url or not role_match:
        return None

    # LinkedIn titles usually start with "Firstname Lastname - Role - Company".
    name = re.split(r"\s(?:-|–|—|\|)\s", title, maxsplit=1)[0].strip()
    name = re.sub(r"\s*\|\s*LinkedIn.*$", "", name, flags=re.IGNORECASE).strip()
    if not name or name.lower() in {"linkedin", "profil linkedin"}:
        return None

    company_words = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", company) if len(w) >= 4]
    company_match = any(word in combined.lower() for word in company_words[:5])
    return {
        "decision_maker_name": name,
        "decision_maker_role": role_match.group(0),
        "decision_maker_linkedin": url,
        "decision_maker_source": url,
        "decision_maker_confidence": "élevée" if company_match else "moyenne",
    }


def enrich_decision_makers(leads: list[dict], country: str = "Bénin") -> int:
    """Add the best public decision-maker match to each lead; return match count."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token or not leads:
        return 0

    query_to_index = {}
    queries = []
    for index, lead in enumerate(leads):
        company = (lead.get("business_name") or "").strip()
        if not company:
            continue
        query = (
            f'site:linkedin.com/in/ "{company}" '
            f'(CEO OR directeur OR fondateur OR gérant OR manager) "{country}"'
        )
        queries.append(query)
        query_to_index[query] = index

    if not queries:
        return 0

    client = ApifyClient(token)
    run = client.actor(GOOGLE_SEARCH_ACTOR).call(run_input={
        "queries": "\n".join(queries),
        "maxPagesPerQuery": 1,
        "countryCode": "bj",
        "languageCode": "fr",
        "mobileResults": False,
        "saveHtml": False,
    })
    dataset_id = _dataset_id(run)
    if not dataset_id:
        return 0

    found = 0
    for item in client.dataset(dataset_id).iterate_items():
        search = item.get("searchQuery", {})
        query = search.get("term", "") if isinstance(search, dict) else str(search)
        index = query_to_index.get(query)
        if index is None:
            continue
        company = leads[index].get("business_name", "")
        for result in item.get("organicResults", []):
            match = _parse_result(result, company)
            if match:
                leads[index].update(match)
                found += 1
                break
    return found
