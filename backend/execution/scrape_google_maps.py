#!/usr/bin/env python3
"""
Scrape Google Maps business listings using Apify's compass/crawler-google-places actor.

Usage:
    python backend/execution/scrape_google_maps.py --search "plumbers in Austin TX" --limit 10
    python backend/execution/scrape_google_maps.py --search "dentists near me" --location "New York, NY" --limit 25
"""

import os
import sys
from pathlib import Path
import json
import argparse
import urllib.request
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

ACTOR_ID = "compass/crawler-google-places"

# Special overrides for regions/countries (not a single city point)
_SPECIAL_LOCATIONS = {
    "île-de-france":  {"coordinates": [2.3522, 48.8566], "radiusKm": 60},
    "ile-de-france":  {"coordinates": [2.3522, 48.8566], "radiusKm": 60},
    "france":         {"coordinates": [1.8883, 46.6034], "radiusKm": 400},
    # Country-wide coverage for Benin. This must be explicit because the French
    # government geocoder used below only covers France.
    "bénin":          {"coordinates": [2.3158, 9.3077], "radiusKm": 350},
    "benin":          {"coordinates": [2.3158, 9.3077], "radiusKm": 350},
}

# Default radius for a city (km). Covers the city + close suburbs.
DEFAULT_CITY_RADIUS_KM = 15


def _geocode_location(location: str) -> dict | None:
    """
    Convert a location name to GeoJSON coordinates + radius.

    Strategy:
    1. Check special overrides (regions, country)
    2. Use the free French government geocoding API (api-adresse.data.gouv.fr)
       which works for any French city, village, or address
    3. Returns {"coordinates": [lng, lat], "radiusKm": N} or None

    The API is free, no key required, and covers all of France including DOM-TOM.
    """
    loc_lower = location.lower().strip()

    # 1. Check special overrides first
    for key, geo in _SPECIAL_LOCATIONS.items():
        if key in loc_lower:
            return geo

    # 2. Geocode via api-adresse.data.gouv.fr
    try:
        params = urllib.parse.urlencode({"q": location, "limit": 1})
        url = f"https://api-adresse.data.gouv.fr/search/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "GMaps-Lead-Pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        if not features:
            print(f"  Warning: geocoding found no results for '{location}', using France-wide fallback")
            return _SPECIAL_LOCATIONS["france"]

        feature = features[0]
        coords = feature["geometry"]["coordinates"]  # [lng, lat] — already GeoJSON order
        props = feature.get("properties", {})
        result_type = props.get("type", "")

        # Adjust radius based on result type
        if result_type == "municipality":
            radius = DEFAULT_CITY_RADIUS_KM
        elif result_type == "street" or result_type == "housenumber":
            radius = 5  # Very precise location
        elif result_type == "locality":
            radius = 10  # Hamlet or neighborhood
        else:
            radius = DEFAULT_CITY_RADIUS_KM

        return {"coordinates": coords, "radiusKm": radius}

    except Exception as e:
        print(f"  Warning: geocoding failed for '{location}': {e}")
        print(f"  Using France-wide fallback")
        return _SPECIAL_LOCATIONS["france"]


def scrape_google_maps(
    search_query: str,
    max_results: int = 10,
    location: str = None,
    language: str = "en",
) -> list[dict]:
    """
    Run the Apify Google Maps scraper actor.

    Args:
        search_query: Search term (e.g., "plumbers in Austin TX")
        max_results: Maximum number of places to scrape
        location: Optional location to focus the search
        language: Language code (default: en)

    Returns:
        List of business dictionaries with scraped data
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("Error: APIFY_API_TOKEN not found in .env", file=sys.stderr)
        return []

    client = ApifyClient(api_token)

    # Build search string with location if provided
    full_search = search_query
    if location and location.lower() not in search_query.lower():
        full_search = f"{search_query} in {location}"

    run_input = {
        "searchStringsArray": [full_search],
        "maxCrawledPlacesPerSearch": max_results,
        "language": language,
        "deeperCityScrape": False,
        "oneReviewPerRow": False,
    }

    # If a location is provided, set custom geolocation (GeoJSON Point + radiusKm)
    # to avoid Apify using its default US-based geolocation.
    # Format: {"type": "Point", "coordinates": [lng, lat], "radiusKm": N}
    if location:
        geo = _geocode_location(location)
        if geo:
            run_input["customGeolocation"] = {
                "type": "Point",
                "coordinates": geo["coordinates"],
                "radiusKm": geo["radiusKm"],
            }
            print(f"Geolocation: {location} -> [{geo['coordinates'][0]:.4f}, {geo['coordinates'][1]:.4f}] r={geo['radiusKm']}km")

    print(f"Starting Google Maps scrape: '{full_search}' (limit: {max_results})...")

    try:
        run = client.actor(ACTOR_ID).call(run_input=run_input)
    except Exception as e:
        print(f"Error running Apify actor: {e}", file=sys.stderr)
        return []

    if not run:
        print("Error: Actor run failed to start", file=sys.stderr)
        return []

    # apify-client 3.x returns a typed Run model; older releases returned a dict.
    dataset_id = getattr(run, "default_dataset_id", None)
    if not dataset_id and isinstance(run, dict):
        dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")
    if not dataset_id:
        print("Error: Apify run did not provide a dataset ID", file=sys.stderr)
        return []

    print(f"Scrape finished. Fetching results from dataset {dataset_id}...")

    results = []
    for item in client.dataset(dataset_id).iterate_items():
        results.append(item)

    print(f"Retrieved {len(results)} businesses from Google Maps")
    return results


def load_apify_dataset(dataset_id: str) -> list[dict]:
    """Load an existing Apify dataset without starting another paid actor run."""
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        return []
    client = ApifyClient(api_token)
    return list(client.dataset(dataset_id).iterate_items())


def save_results(results: list[dict], prefix: str = "gmaps") -> str:
    """Save results to a JSON file in .tmp directory."""
    if not results:
        print("No results to save.")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ".tmp"
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{output_dir}/{prefix}_{timestamp}.json"

    with open(filename, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results saved to {filename}")
    return filename


def main():
    parser = argparse.ArgumentParser(description="Scrape Google Maps businesses using Apify")
    parser.add_argument("--search", required=True, help="Search query (e.g., 'plumbers in Austin TX')")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results (default: 10)")
    parser.add_argument("--location", help="Optional location to focus search")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--output", default="gmaps", help="Output file prefix (default: gmaps)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON to stdout")

    args = parser.parse_args()

    results = scrape_google_maps(
        search_query=args.search,
        max_results=args.limit,
        location=args.location,
        language=args.language,
    )

    if not results:
        print("No results found or error occurred.")
        sys.exit(1)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        filename = save_results(results, prefix=args.output)
        if filename:
            print(f"\nSample result:")
            sample = results[0]
            for key in ["title", "address", "phone", "website", "categoryName"]:
                if key in sample:
                    print(f"  {key}: {sample.get(key)}")


if __name__ == "__main__":
    main()
