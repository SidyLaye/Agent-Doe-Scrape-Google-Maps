#!/usr/bin/env python3
"""
Enrich business leads with French company director (dirigeant) data.

Uses the free French government API (Annuaire des Entreprises) to find
SIREN numbers and director names from business names.

Usage:
    python backend/execution/enrich_dirigeants.py --name "Laforet Lyon"
    python backend/execution/enrich_dirigeants.py --file .tmp/leads.json
"""

import json
import argparse
import time
import urllib.request
import urllib.parse
import urllib.error


API_BASE = "https://recherche-entreprises.api.gouv.fr/search"
REQUEST_DELAY = 0.3  # seconds between requests to be respectful

# Words to strip from Google Maps names to get closer to the legal name
NOISE_WORDS = [
    "agence", "agence immobilière", "agence immobiliere",
    "cabinet", "groupe", "société", "societe",
]

# Patterns like "Lyon 2Ème", "Paris 15e", "Marseille 8ème"
import re
_ARRONDISSEMENT_RE = re.compile(
    r'\b\d{1,2}\s*(?:er|ère|eme|ème|e)\b', re.IGNORECASE
)
_TRAILING_CITY_RE = re.compile(
    r'\b(?:paris|lyon|marseille|bordeaux|toulouse|nantes|nice|lille|strasbourg'
    r'|montpellier|rennes)\b.*$', re.IGNORECASE
)

# ---- Aggressive cleaning patterns (for fallback searches) ----
_LEGAL_FORMS_RE = re.compile(
    r'\b(s\.?a\.?s\.?|e\.?u\.?r\.?l\.?|s\.?a\.?r\.?l\.?|s\.?a\.?|s\.?c\.?i\.?|'
    r'sarl|sas|eurl|sa)\b',
    re.IGNORECASE,
)
# Universal noise words stripped for ALL industries (directions, generic business terms)
_UNIVERSAL_NOISE_RE = re.compile(
    r'\b(sud|nord|est|ouest|services?|ets|etablissement|etablissements|'
    r'center|centre|premium|agent|agence)\b',
    re.IGNORECASE,
)

# ---- Per-industry brand & noise words for aggressive cleaning ----
# Brand words: franchise/brand names that differ from the legal entity name
# Noise words: generic activity descriptors to strip for better API matching
_INDUSTRY_BRAND_WORDS = {
    "auto": {
        "citroën", "citroen", "renault", "peugeot", "mercedes", "fuso", "benz",
        "toyota", "ford", "opel", "fiat", "bmw", "audi", "volkswagen", "vw",
        "dacia", "nissan", "hyundai", "kia", "skoda", "seat", "volvo",
        "réseau", "reseau", "axial", "motrio", "precisium", "norauto",
        "euromaster", "midas", "speedy", "hertz", "sixt", "europcar", "ada",
        "avis", "budget",
    },
    "restaurant": {
        "mcdonald", "mcdonalds", "mcdonald's", "burger king", "kfc",
        "dominos", "domino's", "pizza hut", "subway", "starbucks",
        "paul", "flunch", "hippopotamus", "buffalo grill", "courtepaille",
        "del arte", "la pataterie", "popeyes", "five guys",
    },
    "immobilier": {
        "century 21", "century21", "laforet", "laforêt", "orpi", "guy hoquet",
        "stéphane plaza", "stephane plaza", "foncia", "nexity", "era",
        "iad", "safti", "capifrance", "megagence", "proprietes-privees",
        "solvimo", "square habitat", "avis immobilier",
    },
    "beaute": {
        "franck provost", "jean louis david", "jean-louis david",
        "jacques dessange", "dessange", "camille albane", "mod's hair",
        "tchip", "vog coiffure", "saint algue", "saint-algue",
        "eric stipa", "coiff&co", "hair",
    },
    "btp": {
        "bouygues", "vinci", "eiffage", "colas", "spie", "engie",
        "suez", "veolia",
    },
    "informatique": {
        "capgemini", "atos", "sopra steria", "accenture", "ibm",
        "microsoft", "google", "amazon", "oracle",
    },
    "sante": {
        "doctolib", "ramsay", "elsan", "korian", "orpea",
    },
    "pharmacie": {
        "pharmavie", "giropharm", "alphega", "wellpharma", "lafayette",
        "pharmacie principale",
    },
    "optique": {
        "afflelou", "krys", "optic 2000", "atol", "lissac", "grandoptical",
        "grand optical", "optical center", "lunettes pour tous",
    },
    "veterinaire": set(),
    "fitness": {
        "basic fit", "basic-fit", "fitness park", "keep cool", "neoness",
        "orangetheory", "crossfit", "anytime fitness",
    },
    "education": set(),
    "formation": set(),
    "comptabilite": set(),
    "juridique": set(),
    "assurance": {
        "axa", "allianz", "maif", "macif", "matmut", "groupama",
        "generali", "mma", "maaf", "harmonie mutuelle", "ag2r",
    },
    "banque": {
        "bnp paribas", "societe generale", "credit agricole", "lcl",
        "caisse d'epargne", "banque populaire", "credit mutuel",
        "hsbc", "barclays", "boursorama",
    },
    "transport": {
        "dhl", "fedex", "ups", "chronopost", "geodis", "db schenker",
        "kuehne nagel",
    },
    "logistique": {
        "id logistics", "stef", "norbert dentressangle", "geodis",
    },
    "nettoyage": {
        "onet", "samsic", "atalian", "derichebourg",
    },
    "securite": {
        "securitas", "prosegur", "fiducial", "brinks",
    },
    "hotellerie": {
        "accor", "ibis", "novotel", "mercure", "sofitel", "best western",
        "hilton", "marriott", "campanile", "premiere classe", "b&b hotels",
        "kyriad", "holiday inn",
    },
    "tourisme": set(),
    "commerce_detail": {
        "carrefour", "leclerc", "auchan", "intermarche", "lidl",
        "casino", "monoprix", "franprix", "picard", "biocoop",
    },
    "commerce_gros": set(),
    "textile": {
        "zara", "h&m", "kiabi", "celio", "jules", "camaieu",
    },
    "agriculture": set(),
    "industrie": set(),
    "energie": {
        "edf", "engie", "total", "totalenergies",
    },
    "telecom": {
        "orange", "sfr", "bouygues telecom", "free",
    },
    "media": set(),
    "culture": set(),
    "sport": {
        "decathlon", "intersport", "go sport", "sport 2000",
    },
    "demenagement": set(),
    "funeraire": {
        "pompes funebres", "roc eclerc", "pfg",
    },
    "jardinerie": {
        "jardiland", "gamm vert", "truffaut", "botanic",
    },
    "animalerie": {
        "animalis", "maxi zoo", "truffaut",
    },
    "pressing": {
        "5asec", "pressing de france",
    },
}

_INDUSTRY_NOISE_WORDS = {
    "auto": {
        "garage", "gge", "auto", "automobile", "automobiles", "automotive",
        "location", "camping-car", "campingcar", "occasion", "occasions",
        "carrosserie", "depannage", "assistance", "reparation", "entretien",
        "vidange", "controle", "technique", "mecanique", "pneumatique",
    },
    "restaurant": {
        "restaurant", "brasserie", "bistro", "bistrot", "pizzeria",
        "trattoria", "snack", "sandwicherie", "creperie", "grill",
        "rotisserie", "livraison", "a emporter",
    },
    "immobilier": {
        "immobilier", "immobiliere", "immobilières", "immobilieres",
        "transaction", "gestion", "locative", "syndic", "location",
        "foncier", "fonciere", "promotion",
    },
    "beaute": {
        "coiffure", "coiffeur", "salon", "institut", "beaute",
        "esthetique", "onglerie", "manucure", "barbier", "barber",
    },
    "btp": {
        "construction", "maconnerie", "plomberie", "electricite",
        "charpente", "couverture", "toiture", "peinture",
        "carrelage", "menuiserie", "serrurerie", "travaux",
    },
    "informatique": {
        "informatique", "developpement", "logiciel", "software",
        "consulting", "conseil", "digital", "numerique",
    },
    "sante": {
        "clinique", "hopital", "cabinet", "medical", "medecin",
        "docteur", "praticien", "soin", "soins",
    },
    "pharmacie": {
        "pharmacie", "parapharmacie", "officine",
    },
    "optique": {
        "opticien", "optique", "lunettes", "lentilles",
    },
    "veterinaire": {
        "veterinaire", "clinique veterinaire", "cabinet veterinaire",
    },
    "fitness": {
        "fitness", "musculation", "sport", "coaching", "coach",
    },
    "education": {
        "ecole", "college", "lycee", "formation", "enseignement",
    },
    "formation": {
        "formation", "organisme", "stage", "apprentissage",
    },
    "comptabilite": {
        "comptable", "comptabilite", "expertise", "expert",
    },
    "juridique": {
        "avocat", "juridique", "notaire", "huissier", "cabinet",
    },
    "assurance": {
        "assurance", "assurances", "mutuelle", "prevoyance", "courtage",
    },
    "banque": {
        "banque", "bancaire", "credit", "financement", "epargne",
    },
    "transport": {
        "transport", "transporteur", "livraison", "logistique",
        "messagerie", "fret", "expedition",
    },
    "logistique": {
        "logistique", "entreposage", "stockage", "supply chain",
    },
    "nettoyage": {
        "nettoyage", "proprete", "entretien", "menage",
    },
    "securite": {
        "securite", "gardiennage", "surveillance", "vigile",
    },
    "hotellerie": {
        "hotel", "hotellerie", "hebergement", "chambre", "residence",
    },
    "tourisme": {
        "tourisme", "voyage", "voyages", "agence de voyage", "sejour",
    },
    "commerce_detail": {
        "supermarche", "magasin", "boutique", "epicerie", "alimentation",
    },
    "commerce_gros": {
        "grossiste", "negoce", "distribution",
    },
    "textile": {
        "vetement", "vetements", "mode", "pret-a-porter", "confection",
    },
    "agriculture": {
        "agricole", "exploitation", "ferme", "elevage", "culture",
    },
    "industrie": {
        "usine", "fabrication", "industriel", "production", "manufacture",
    },
    "energie": {
        "energie", "energies", "solaire", "photovoltaique", "eolien",
    },
    "telecom": {
        "telecom", "telecommunications", "telephonie", "fibre", "internet",
    },
    "media": {
        "media", "presse", "edition", "publication", "audiovisuel",
    },
    "culture": {
        "theatre", "musee", "galerie", "spectacle", "evenementiel",
    },
    "sport": {
        "sport", "sportif", "equipement", "articles de sport",
    },
    "demenagement": {
        "demenagement", "demenageur", "garde-meuble",
    },
    "funeraire": {
        "funeraire", "obseques", "pompes funebres", "crematorium",
    },
    "jardinerie": {
        "jardinerie", "pepiniere", "paysagiste", "jardin",
    },
    "animalerie": {
        "animalerie", "animaux", "chien", "chat",
    },
    "pressing": {
        "pressing", "teinturerie", "blanchisserie", "laverie",
    },
}
_PARENS_RE = re.compile(r'\([^)]*\)')
_SEPARATOR_RE = re.compile(r'\s*[-–—/]\s*')
_DEPT_NUMBER_RE = re.compile(r'\b\d{2,3}\b')  # trailing dept numbers like "60", "77"

# ---- NAF/APE activity code validation (covers all major sectors) ----
# Each industry has:
#   matching_naf:    NAF prefixes that CONFIRM the business is in this industry (+10)
#   conflicting_naf: NAF prefixes that CONTRADICT this industry (-50)
# If the gmaps_category doesn't match any known industry, NAF validation is skipped (safe default).
_INDUSTRY_NAF_MAP = {
    "auto": {
        "matching_naf": {"45.", "77.11", "29.1", "49.3"},
        "conflicting_naf": {"96.", "56.", "68.", "86.", "85.", "62.", "55."},
    },
    "restaurant": {
        "matching_naf": {"56.", "10.7", "10.1"},
        "conflicting_naf": {"45.", "68.", "96.", "62.", "41.", "42.", "43."},
    },
    "immobilier": {
        "matching_naf": {"68.", "41.1"},
        "conflicting_naf": {"45.", "56.", "96.", "62.", "86.", "85."},
    },
    "beaute": {
        "matching_naf": {"96.02", "96.04", "96.09"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "41.", "42.", "43."},
    },
    "btp": {
        "matching_naf": {"41.", "42.", "43.", "71.1"},
        "conflicting_naf": {"45.", "56.", "68.", "96.", "62.", "86."},
    },
    "informatique": {
        "matching_naf": {"62.", "63.", "58.2"},
        "conflicting_naf": {"45.", "56.", "68.", "96.", "41.", "42.", "43."},
    },
    "sante": {
        "matching_naf": {"86.", "87.", "88."},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "pharmacie": {
        "matching_naf": {"47.73"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "62."},
    },
    "optique": {
        "matching_naf": {"47.78"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "62."},
    },
    "veterinaire": {
        "matching_naf": {"75."},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "62."},
    },
    "fitness": {
        "matching_naf": {"93.1", "93.04", "96.04"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "62."},
    },
    "education": {
        "matching_naf": {"85."},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "formation": {
        "matching_naf": {"85.5", "85.4"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "comptabilite": {
        "matching_naf": {"69.20"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "juridique": {
        "matching_naf": {"69.10"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "assurance": {
        "matching_naf": {"65.", "66.2"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "banque": {
        "matching_naf": {"64.", "66.1"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43.", "96."},
    },
    "transport": {
        "matching_naf": {"49.", "50.", "51.", "52.", "53."},
        "conflicting_naf": {"56.", "68.", "96.", "62.", "86."},
    },
    "logistique": {
        "matching_naf": {"52.", "49.4"},
        "conflicting_naf": {"56.", "68.", "96.", "62.", "86."},
    },
    "nettoyage": {
        "matching_naf": {"81.2"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "securite": {
        "matching_naf": {"80.1", "80.2"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86.", "96."},
    },
    "hotellerie": {
        "matching_naf": {"55."},
        "conflicting_naf": {"45.", "68.", "96.", "62.", "41.", "42.", "43."},
    },
    "tourisme": {
        "matching_naf": {"79.", "55."},
        "conflicting_naf": {"45.", "68.", "96.", "41.", "42.", "43."},
    },
    "commerce_detail": {
        "matching_naf": {"47."},
        "conflicting_naf": {"45.", "68.", "62.", "86.", "41.", "42.", "43."},
    },
    "commerce_gros": {
        "matching_naf": {"46."},
        "conflicting_naf": {"68.", "62.", "86.", "96."},
    },
    "textile": {
        "matching_naf": {"47.71", "14.", "13."},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "agriculture": {
        "matching_naf": {"01.", "02.", "03."},
        "conflicting_naf": {"62.", "68.", "86.", "96.", "56."},
    },
    "industrie": {
        "matching_naf": {"10.", "11.", "12.", "13.", "14.", "15.", "16.", "17.",
                         "18.", "19.", "20.", "21.", "22.", "23.", "24.", "25.",
                         "26.", "27.", "28.", "29.", "30.", "31.", "32.", "33."},
        "conflicting_naf": {"68.", "86.", "96.", "85."},
    },
    "energie": {
        "matching_naf": {"35."},
        "conflicting_naf": {"56.", "68.", "96.", "86."},
    },
    "telecom": {
        "matching_naf": {"61."},
        "conflicting_naf": {"45.", "56.", "68.", "96.", "86."},
    },
    "media": {
        "matching_naf": {"58.", "59.", "60."},
        "conflicting_naf": {"45.", "56.", "68.", "96."},
    },
    "culture": {
        "matching_naf": {"90.", "91.", "93.2"},
        "conflicting_naf": {"45.", "56.", "68.", "41.", "42.", "43."},
    },
    "sport": {
        "matching_naf": {"93.1", "47.64"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "demenagement": {
        "matching_naf": {"49.42"},
        "conflicting_naf": {"56.", "68.", "96.", "62.", "86."},
    },
    "funeraire": {
        "matching_naf": {"96.03"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "jardinerie": {
        "matching_naf": {"47.76", "01.3", "81.30"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "animalerie": {
        "matching_naf": {"47.76"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
    "pressing": {
        "matching_naf": {"96.01"},
        "conflicting_naf": {"45.", "56.", "68.", "62.", "86."},
    },
}

# Maps industry slug -> set of keywords to detect from gmaps_category
# NOTE: Keywords must include BOTH accented and unaccented versions because
# Google Maps sends accented categories (e.g. "immobilière", "vétérinaire")
# and .lower() preserves accents.
#
# IMPORTANT: More specific industries must be checked BEFORE generic ones.
# The _INDUSTRY_KEYWORDS_ORDER list controls matching priority:
# e.g. "veterinaire" must match before "sante" (both contain "clinique").

_INDUSTRY_KEYWORDS = {
    "auto": {
        "auto", "car", "voiture", "garage", "concessionnaire", "automobile",
        "moto", "vehicule", "véhicule", "dealer", "camping-car", "carrosserie",
        "pneumatique", "pneu", "vidange", "depannage", "dépannage", "remorquage",
        "mecanique", "mécanique", "controle technique", "contrôle technique",
    },
    "restaurant": {
        "restaurant", "brasserie", "bistro", "bistrot", "pizzeria", "trattoria",
        "sushi", "ramen", "burger", "fast food", "fast-food", "snack",
        "sandwicherie", "boulangerie", "traiteur", "bar", "pub",
        "tapas", "kebab", "buffet", "crêperie", "creperie", "glacier",
    },
    "immobilier": {
        "immobilier", "immobilière", "immobiliere", "agence immobiliere",
        "agence immobilière", "promoteur", "foncier",
        "transaction immobiliere", "gestion locative", "syndic",
    },
    "beaute": {
        "coiffeur", "coiffure", "salon de coiffure", "barbier", "barber",
        "esthetique", "esthétique", "spa", "institut de beaute",
        "institut de beauté", "onglerie", "manucure",
        "beaute", "beauté", "beauty",
    },
    "btp": {
        "btp", "construction", "maconnerie", "maçonnerie",
        "plomberie", "electricite", "électricité",
        "electricien", "électricien", "charpente", "couverture",
        "toiture", "peinture", "carrelage", "menuiserie", "serrurerie",
        "chauffage", "climatisation", "architecte", "travaux",
    },
    "informatique": {
        "informatique", "developpeur", "développeur",
        "developpement web", "développement web",
        "agence web", "agence digitale", "logiciel", "software",
        "ssii", "esn", "consultant informatique", "programmation",
    },
    # --- More specific must come before generic "sante" ---
    "veterinaire": {
        "veterinaire", "vétérinaire",
        "clinique veterinaire", "clinique vétérinaire",
        "cabinet veterinaire", "cabinet vétérinaire",
    },
    "pharmacie": {
        "pharmacie", "parapharmacie",
    },
    "optique": {
        "opticien", "optique", "lunettes",
    },
    "sante": {
        "medecin", "médecin", "docteur", "clinique", "hopital", "hôpital",
        "cabinet medical", "cabinet médical",
        "centre de sante", "centre de santé",
        "kinesitherapeute", "kinésithérapeute", "kine", "kiné",
        "osteopathe", "ostéopathe",
        "dentiste", "chirurgien", "dermatologue", "cardiologue",
        "radiologue", "ophtalmo", "ophtalmologue", "gynecologue", "gynécologue",
        "pediatre", "pédiatre", "psychiatre", "psychologue", "infirmier",
        "sage-femme", "orthophoniste", "podologue",
    },
    "fitness": {
        "fitness", "salle de sport", "musculation", "gym", "crossfit",
        "coach sportif", "club de sport",
    },
    # --- "formation" before "education" (auto-école = formation, not education) ---
    "formation": {
        "formation", "centre de formation", "organisme de formation",
        "coaching", "auto-ecole", "auto ecole", "auto-école",
    },
    "education": {
        "ecole", "école", "college", "collège", "lycee", "lycée",
        "universite", "université", "enseignement",
        "creche", "crèche", "garderie", "maternelle",
    },
    "comptabilite": {
        "expert-comptable", "expert comptable", "comptable",
        "cabinet comptable", "expertise comptable",
    },
    "juridique": {
        "avocat", "notaire", "huissier", "cabinet d'avocat",
        "conseil juridique", "juriste",
    },
    "assurance": {
        "assurance", "assureur", "courtier en assurance", "mutuelle",
    },
    "banque": {
        "banque", "credit", "crédit", "courtier en pret",
        "courtier en prêt", "pret immobilier", "prêt immobilier",
        "financement",
    },
    # --- "demenagement" before "transport" (both contain transport-like keywords) ---
    "demenagement": {
        "demenagement", "déménagement", "demenageur", "déménageur",
    },
    "transport": {
        "transport", "transporteur", "livraison", "coursier",
        "taxi", "vtc", "ambulance",
    },
    "logistique": {
        "logistique", "entrepot", "entrepôt", "entreposage", "supply chain",
    },
    "nettoyage": {
        "nettoyage", "proprete", "propreté", "menage", "ménage",
        "societe de nettoyage", "société de nettoyage",
    },
    "securite": {
        "securite", "sécurité", "gardiennage", "surveillance", "vigile",
        "alarme", "telesurveillance", "télésurveillance",
        "agent de securite", "agent de sécurité",
    },
    "hotellerie": {
        "hotel", "hôtel", "auberge", "chambre d'hotes", "chambre d'hôtes",
        "gite", "gîte", "residence hoteliere", "résidence hôtelière",
        "apart hotel",
    },
    "tourisme": {
        "agence de voyage", "tourisme", "tour operator",
        "office de tourisme",
    },
    "commerce_detail": {
        "supermarche", "supermarché", "hypermarche", "hypermarché",
        "epicerie", "épicerie", "magasin",
        "superette", "supérette", "alimentation",
        "commerce de detail", "commerce de détail",
    },
    "commerce_gros": {
        "grossiste", "negoce", "négoce", "import", "export",
        "commerce de gros", "distribution",
    },
    "textile": {
        "vetement", "vêtement", "mode", "pret-a-porter", "prêt-à-porter",
        "textile", "confection", "mercerie", "tissu",
    },
    "agriculture": {
        "agricole", "exploitation agricole", "ferme", "elevage", "élevage",
        "viticulteur", "vigneron", "maraicher", "maraîcher",
        "pepiniere", "pépinière",
    },
    "industrie": {
        "usine", "fabrication", "industriel", "manufacture",
        "atelier", "production industrielle",
    },
    "energie": {
        "energie", "énergie", "solaire", "photovoltaique", "photovoltaïque",
        "eolien", "éolien", "installateur", "panneau solaire", "chauffagiste",
    },
    "telecom": {
        "telecom", "télécom", "telephonie", "téléphonie",
        "fibre", "operateur", "opérateur", "fournisseur internet",
    },
    "media": {
        "media", "média", "presse", "edition", "édition",
        "journal", "magazine", "production audiovisuelle", "studio",
    },
    "culture": {
        "theatre", "théâtre", "musee", "musée", "galerie",
        "spectacle", "evenementiel", "événementiel",
        "cinema", "cinéma", "concert",
    },
    "sport": {
        "magasin de sport", "articles de sport",
        "equipement sportif", "équipement sportif", "club sportif",
    },
    "funeraire": {
        "funeraire", "funéraire", "pompes funebres", "pompes funèbres",
        "obseques", "obsèques", "crematorium", "crématorium",
        "marbrerie funeraire", "marbrerie funéraire",
    },
    "jardinerie": {
        "jardinerie", "pepiniere", "pépinière",
        "paysagiste", "jardinier", "espaces verts", "entretien jardin",
    },
    "animalerie": {
        "animalerie", "animaux", "toilettage",
    },
    "pressing": {
        "pressing", "teinturerie", "laverie", "blanchisserie",
    },
}

# Priority order for industry detection. More specific industries MUST come
# before generic ones to avoid false matches (e.g. "clinique vétérinaire"
# must match "veterinaire" before "sante" which also has "clinique").
_INDUSTRY_KEYWORDS_ORDER = [
    # Specific niche industries first (avoid matching generic keywords)
    "veterinaire", "pharmacie", "optique",
    "formation", "demenagement", "funeraire", "pressing",
    "animalerie", "jardinerie",
    # Sport before commerce_detail ("magasin de sport" != supermarché)
    "sport",
    # Core industries
    "auto", "restaurant", "immobilier", "beaute", "btp", "informatique",
    "sante", "fitness", "education",
    "comptabilite", "juridique", "assurance", "banque",
    "transport", "logistique", "nettoyage", "securite",
    "hotellerie", "tourisme",
    # Generic commerce last (many keywords overlap with other sectors)
    "commerce_detail", "commerce_gros", "textile",
    "agriculture", "industrie", "energie", "telecom",
    "media", "culture",
]


def _detect_industry(gmaps_category: str | None) -> tuple[str, dict] | tuple[None, None]:
    """
    Given a Google Maps category, return (slug, naf_config) for the matching
    industry, or (None, None) if the category doesn't match any known industry.
    (None, None) -> NAF validation + industry-specific cleaning are skipped.

    Uses _INDUSTRY_KEYWORDS_ORDER to check specific industries before generic
    ones (e.g. "veterinaire" before "sante").
    """
    if not gmaps_category:
        return None, None
    cat_lower = gmaps_category.lower()
    for industry_slug in _INDUSTRY_KEYWORDS_ORDER:
        keywords = _INDUSTRY_KEYWORDS.get(industry_slug, set())
        if any(kw in cat_lower for kw in keywords):
            naf_config = _INDUSTRY_NAF_MAP.get(industry_slug)
            if naf_config:
                return industry_slug, naf_config
    return None, None


def _clean_business_name(name: str) -> str:
    """
    Strip noise from a Google Maps business name to improve API matching.
    'Agence immobilière Laforêt Lyon 2Ème' -> 'Laforêt'
    'Agence Immobilière - Hosman' -> 'Hosman'
    """
    cleaned = name.strip()
    # Remove arrondissement patterns first
    cleaned = _ARRONDISSEMENT_RE.sub("", cleaned)
    # Remove common noise prefixes (may appear with separators like " - ")
    lower = cleaned.lower()
    for noise in sorted(NOISE_WORDS, key=len, reverse=True):
        if lower.startswith(noise):
            cleaned = cleaned[len(noise):].strip(" -–—")
            lower = cleaned.lower()
    # Strip leading/trailing punctuation and separators
    cleaned = cleaned.strip(" -–—,.")
    return cleaned


def _aggressive_clean(name: str, gmaps_category: str = None) -> str:
    """
    Much more aggressive cleaning: strips brands, legal forms, generic words.
    Used as a last-resort search variant when normal cleaning fails.
    'GARAGE GIBERT CHRISTIAN - Citroën' -> 'GIBERT CHRISTIAN'
    'MERCEDES FUSO - S.A.S. RAMBACH' -> 'RAMBACH'

    Cleaning is industry-aware:
    - Brand words and noise words are per-industry (auto brands only for auto, etc.)
    - When no category is provided (CLI usage), auto brands + auto noise are used
      as fallback for backward compatibility.
    - Universal noise (directions, generic terms) is always stripped.
    """
    c = name.strip()
    c = _PARENS_RE.sub("", c)
    c = _LEGAL_FORMS_RE.sub("", c)

    # Determine industry and apply matching brand + noise words
    slug, _ = _detect_industry(gmaps_category)

    # Build the set of words to strip
    brand_words = set()
    noise_words = set()
    if slug:
        # Known industry: use that industry's brand + noise words
        brand_words = _INDUSTRY_BRAND_WORDS.get(slug, set())
        noise_words = _INDUSTRY_NOISE_WORDS.get(slug, set())
    elif gmaps_category is None:
        # No category at all (CLI mode): fallback to auto for backward compat
        brand_words = _INDUSTRY_BRAND_WORDS.get("auto", set())
        noise_words = _INDUSTRY_NOISE_WORDS.get("auto", set())
    # else: category provided but unknown industry -> only universal noise

    # Strip brand words (case-insensitive word boundary)
    if brand_words:
        # Sort longest first to avoid partial matches
        sorted_brands = sorted(brand_words, key=len, reverse=True)
        brand_pattern = r'\b(' + '|'.join(re.escape(b) for b in sorted_brands) + r')\b'
        c = re.sub(brand_pattern, '', c, flags=re.IGNORECASE)

    # Strip industry-specific noise words
    if noise_words:
        sorted_noise = sorted(noise_words, key=len, reverse=True)
        noise_pattern = r'\b(' + '|'.join(re.escape(n) for n in sorted_noise) + r')\b'
        c = re.sub(noise_pattern, '', c, flags=re.IGNORECASE)

    # Always strip universal noise (directions, generic terms)
    c = _UNIVERSAL_NOISE_RE.sub("", c)
    c = _DEPT_NUMBER_RE.sub("", c)
    # Split on separators and take the longest meaningful part
    parts = _SEPARATOR_RE.split(c)
    parts = [p.strip(" -–—,.") for p in parts if len(p.strip(" -–—,.")) >= 2]
    if parts:
        parts.sort(key=len, reverse=True)
        c = parts[0]
    c = re.sub(r'\s+', ' ', c).strip(" -–—,.")
    return c


def _build_search_variants(business_name: str, gmaps_category: str = None) -> list[str]:
    """
    Build multiple search queries from a business name, from most specific
    to most relaxed, to increase chances of a match.
    """
    variants = []
    # 1. Original name as-is
    variants.append(business_name)
    # 2. Cleaned name (no noise words, no arrondissement)
    cleaned = _clean_business_name(business_name)
    if cleaned and cleaned != business_name:
        variants.append(cleaned)
    # 3. Cleaned name without trailing city
    no_city = _TRAILING_CITY_RE.sub("", cleaned).strip(" -–—,.")
    if no_city and no_city != cleaned and len(no_city) >= 3:
        variants.append(no_city)
    # 4. Aggressive clean (strips brands, legal forms, generic words)
    aggressive = _aggressive_clean(business_name, gmaps_category=gmaps_category)
    if aggressive and len(aggressive) >= 3:
        variants.append(aggressive)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in variants:
        key = v.lower().strip()
        if key not in seen and len(key) >= 2:
            seen.add(key)
            unique.append(v)
    return unique


def _api_search(query: str, code_postal: str = None) -> list[dict]:
    """Raw API call. Returns list of result dicts."""
    params = {"q": query, "page": "1", "per_page": "5"}
    if code_postal:
        params["code_postal"] = code_postal

    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GMapsLeadPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"    API error for '{query}': {e}")
        return []

    return data.get("results", [])


def _get_result_department(result: dict) -> str:
    """Extract the department code from an API result's siege address."""
    siege = result.get("siege", {})
    cp = siege.get("code_postal", "")
    if cp and len(cp) >= 2:
        return cp[:2]
    return ""


def _has_etablissement_in_dept(result: dict, expected_dept: str) -> bool:
    """
    Check if the company has ANY etablissement in the expected department,
    not just the siege. A company's siege may be elsewhere but they can have
    a branch/agency in the target department.
    """
    if not expected_dept:
        return False
    # Check siege first
    siege_dept = _get_result_department(result)
    if siege_dept == expected_dept:
        return True
    # Check matching_etablissements
    for etab in result.get("matching_etablissements", []):
        cp = etab.get("code_postal", "")
        if cp and len(cp) >= 2 and cp[:2] == expected_dept:
            return True
    return False


def _get_naf_code(result: dict) -> str:
    """Get the NAF/APE activity code from the result's siege."""
    siege = result.get("siege", {})
    return siege.get("activite_principale", "") or ""


def _naf_matches(naf: str, prefixes: set) -> bool:
    """Check if a NAF code starts with any of the given prefixes."""
    if not naf or not prefixes:
        return False
    return any(naf.startswith(p) for p in prefixes)


def _score_result(result: dict, original_name: str, expected_dept: str = None,
                  gmaps_category: str = None) -> float:
    """
    Score how well an API result matches the original business name.
    If expected_dept is provided, results in the wrong department are penalized.
    If gmaps_category matches a known industry, NAF code validation is applied.
    """
    score = 0.0
    nom = (result.get("nom_complet") or "").lower()
    # Also check the "nom_raison_sociale" field and enseignes
    noms_all = nom
    for ens in result.get("matching_etablissements", []):
        noms_all += " " + (ens.get("nom_commercial") or "").lower()

    cleaned_lower = _clean_business_name(original_name).lower()
    aggressive_lower = _aggressive_clean(original_name, gmaps_category=gmaps_category).lower()

    # Active company bonus
    if result.get("etat_administratif") == "A":
        score += 10

    # Name overlap: check key words against the result name
    # Use aggressive-cleaned words for more precise matching
    key_words = [w for w in aggressive_lower.split() if len(w) >= 3]
    if not key_words:
        key_words = [w for w in cleaned_lower.split() if len(w) >= 3]
    if key_words:
        matches = sum(1 for w in key_words if w in noms_all)
        score += (matches / len(key_words)) * 25

    # Exact name containment bonus
    if aggressive_lower and aggressive_lower in nom:
        score += 15

    # Has dirigeants bonus
    if result.get("dirigeants"):
        has_person = any(
            d.get("type_dirigeant") == "personne physique"
            for d in result["dirigeants"]
        )
        score += 5 if has_person else 2

    # Department validation: check both siege AND etablissements
    if expected_dept:
        has_etab_in_dept = _has_etablissement_in_dept(result, expected_dept)
        result_dept = _get_result_department(result)
        if has_etab_in_dept:
            score += 8  # Company has presence in expected department
        elif result_dept and result_dept != expected_dept:
            score -= 30  # No presence at all in expected department

    # NAF/APE activity validation (generic, works for any known industry)
    naf = _get_naf_code(result)
    if naf and gmaps_category:
        _, industry_config = _detect_industry(gmaps_category)
        if industry_config:  # None = unknown industry -> skip NAF validation
            if _naf_matches(naf, industry_config["matching_naf"]):
                score += 10   # NAF confirms the expected industry
            elif _naf_matches(naf, industry_config["conflicting_naf"]):
                score -= 50   # NAF clearly contradicts the expected industry

    # Zero key-word overlap penalty: if aggressive-cleaned name has words
    # and NONE of them appear in the result, this is likely a false match
    if key_words and all(w not in noms_all for w in key_words):
        nom_complet = (result.get("nom_complet") or "").lower()
        if all(w not in nom_complet for w in key_words):
            score -= 15

    # Weak identity guard: if aggressive cleaning left only very common/short
    # fragments (like city names, directions), the match is unreliable
    _CITY_FRAGMENTS = {"paris", "lyon", "marseille", "lille", "bordeaux",
                       "toulouse", "nantes", "nice", "strasbourg", "rennes",
                       "montpellier", "sud", "nord", "est", "ouest",
                       "ile", "france", "moto", "new"}
    if key_words:
        meaningful = [w for w in key_words if w not in _CITY_FRAGMENTS and len(w) >= 3]
        if not meaningful:
            score -= 30  # Only generic/city words → very unreliable match

    return score


def search_entreprise(business_name: str, code_postal: str = None,
                      gmaps_category: str = None) -> dict | None:
    """
    Search the French government API for a business by name.

    Multi-tier strategy:
      Tier 1: Search variants WITH zip code filter (most precise)
      Tier 2: Search variants WITHOUT zip code (broader, catches name mismatches)
      Tier 3: Department-code filter only (via code_postal[:2]xx00 pattern)

    Results are scored with department + NAF validation to avoid false positives.
    Returns the best matching result or None.
    """
    variants = _build_search_variants(business_name, gmaps_category=gmaps_category)
    expected_dept = code_postal[:2] if code_postal and len(code_postal) >= 2 else None
    all_results = []
    seen_sirens = set()

    def _collect(results):
        added = 0
        for r in results:
            siren = r.get("siren")
            if siren and siren not in seen_sirens:
                seen_sirens.add(siren)
                all_results.append(r)
                added += 1
        return added

    # ---- Tier 1: with zip code ----
    if code_postal:
        for variant in variants:
            results = _api_search(variant, code_postal=code_postal)
            _collect(results)
            time.sleep(REQUEST_DELAY)
            if all_results:
                break

    # Check if Tier 1 found anything promising (score above threshold)
    tier1_promising = False
    if all_results:
        tier1_scores = [_score_result(r, business_name, expected_dept=expected_dept,
                                      gmaps_category=gmaps_category) for r in all_results]
        tier1_promising = max(tier1_scores) >= 15

    # ---- Tier 2: without zip code (if tier 1 found nothing promising) ----
    if not tier1_promising:
        for variant in variants:
            results = _api_search(variant)
            _collect(results)
            time.sleep(REQUEST_DELAY)
            if len(all_results) > (5 if not tier1_promising else 0):
                # Try one more variant for diversity
                if variant == variants[0] and len(variants) > 1:
                    continue
                break

    if not all_results:
        return None

    # Score all results with department + NAF validation
    scored = [(r, _score_result(r, business_name, expected_dept=expected_dept,
                                gmaps_category=gmaps_category)) for r in all_results]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_result, best_score = scored[0]

    # Reject if score is too low (likely a false positive)
    if best_score < 15:
        return None

    # Extra validation: if best result is in a completely different department
    # AND the score is marginal, reject it
    if expected_dept:
        result_dept = _get_result_department(best_result)
        if result_dept and result_dept != expected_dept and best_score < 25:
            return None

    return best_result


def resolve_personne_morale(siren: str, denomination: str = "") -> list[dict]:
    """
    When a director is a legal entity (personne morale), look up that
    entity to find the actual person behind it.
    Tries SIREN search first, falls back to denomination search.
    """
    # Try by denomination (more reliable than siren: prefix)
    if denomination:
        results = _api_search(denomination)
        # Find the one matching our SIREN
        for r in results:
            if r.get("siren") == siren:
                return r.get("dirigeants", [])
        # If no SIREN match, return first active result's dirigeants
        active = [r for r in results if r.get("etat_administratif") == "A"]
        if active:
            return active[0].get("dirigeants", [])

    # Fallback: try siren: prefix search
    results = _api_search(f"siren:{siren}")
    if results:
        return results[0].get("dirigeants", [])

    return []


def extract_dirigeants(entreprise: dict, max_depth: int = 2) -> list[dict]:
    """
    Extract director information from an entreprise result.
    If the director is a legal entity, recursively resolve to find
    the physical person (up to max_depth).

    Returns a list of dicts with keys: nom, prenoms, qualite, type.
    """
    raw_dirigeants = entreprise.get("dirigeants", [])
    result = []

    for d in raw_dirigeants:
        # Skip auditors — we want the actual directors
        qualite = (d.get("qualite") or "").lower()
        if "commissaire" in qualite:
            continue

        if d.get("type_dirigeant") == "personne physique":
            result.append({
                "nom": d.get("nom", ""),
                "prenoms": d.get("prenoms", ""),
                "qualite": d.get("qualite", ""),
                "type": "personne physique",
            })
        elif d.get("type_dirigeant") == "personne morale" and max_depth > 0:
            # Try to resolve the legal entity to find the real person
            siren_pm = d.get("siren", "")
            denomination = d.get("denomination", "")
            if siren_pm or denomination:
                time.sleep(REQUEST_DELAY)
                sub_dirigeants = resolve_personne_morale(siren_pm, denomination)
                found_person = False
                for sd in sub_dirigeants:
                    sd_qualite = (sd.get("qualite") or "").lower()
                    if "commissaire" in sd_qualite:
                        continue
                    if sd.get("type_dirigeant") == "personne physique":
                        result.append({
                            "nom": sd.get("nom", ""),
                            "prenoms": sd.get("prenoms", ""),
                            "qualite": sd.get("qualite", ""),
                            "type": "personne physique",
                            "via": denomination,
                        })
                        found_person = True
                if not found_person:
                    # Keep the legal entity as-is
                    result.append({
                        "nom": denomination,
                        "prenoms": "",
                        "qualite": d.get("qualite", ""),
                        "type": "personne morale",
                    })
            else:
                result.append({
                    "nom": denomination,
                    "prenoms": "",
                    "qualite": d.get("qualite", ""),
                    "type": "personne morale",
                })

    return result


_SIREN_RE = re.compile(
    r'(?:SIREN|RCS|immatricul)[^0-9]{0,30}(\d{3}[\s.]?\d{3}[\s.]?\d{3})',
    re.IGNORECASE,
)
_SIRET_RE = re.compile(
    r'(?:SIRET)[^0-9]{0,20}(\d{3}[\s.]?\d{3}[\s.]?\d{3}[\s.]?\d{5})',
    re.IGNORECASE,
)

_LEGAL_PAGES = ["", "/mentions-legales", "/mentions-legales/", "/cgu", "/legal"]
# Additional pages only tried with Playwright (JS-rendered sites)
_LEGAL_PAGES_EXTENDED = ["/mention-legale", "/politique-de-confidentialite"]


def _extract_siren_from_html(html: str) -> str | None:
    """Extract SIREN from an HTML string."""
    m = _SIRET_RE.search(html)
    if m:
        raw = m.group(1).replace(" ", "").replace(".", "")
        return raw[:9]
    m = _SIREN_RE.search(html)
    if m:
        raw = m.group(1).replace(" ", "").replace(".", "")
        return raw
    return None


def _scrape_siren_from_website(website: str) -> str | None:
    """
    Try to find a SIREN/SIRET number on the company website.
    Strategy:
    1. Fast pass: urllib on homepage + common legal pages (static HTML)
    2. Slow pass: Playwright headless browser for JS-rendered sites
    """
    if not website:
        return None

    base = website.rstrip("/")
    # Strip UTM params and other tracking
    if "?" in base:
        base = base.split("?")[0]

    # --- Fast pass: static HTML with urllib ---
    for suffix in _LEGAL_PAGES:
        url = base + suffix
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LeadEnricher/1.0)",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            continue

        siren = _extract_siren_from_html(html)
        if siren:
            return siren

    # --- Slow pass: Playwright for JS-rendered pages ---
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    all_suffixes = _LEGAL_PAGES + _LEGAL_PAGES_EXTENDED
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for suffix in all_suffixes:
                url = base + suffix
                try:
                    page.goto(url, timeout=12000)
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    continue
                html = page.content()
                siren = _extract_siren_from_html(html)
                if siren:
                    browser.close()
                    return siren
            browser.close()
    except Exception:
        pass

    return None


def _enrich_from_siren(siren: str) -> tuple[dict | None, list[dict]]:
    """Look up an entreprise by SIREN and extract dirigeants."""
    results = _api_search(siren)
    for r in results:
        if r.get("siren") == siren:
            return r, extract_dirigeants(r)
    return None, []


def enrich_lead(business_name: str, zip_code: str = None, website: str = None,
                gmaps_category: str = None) -> dict:
    """
    Enrich a single lead with dirigeant data.

    Strategy:
    1. Search by business name in the government API (with NAF validation)
    2. If no result or no person found, try scraping SIREN from the website
    3. If SIREN found on website, look up the company directly

    Args:
        gmaps_category: Google Maps category (e.g. "Concessionnaire automobile")
            used for NAF cross-validation to reject false positives.

    Returns a dict with enrichment fields:
        siren, dirigeant_nom, dirigeant_prenom, dirigeant_qualite,
        dirigeant_type, nom_raison_sociale
    """
    empty = {
        "siren": "",
        "nom_raison_sociale": "",
        "dirigeant_nom": "",
        "dirigeant_prenom": "",
        "dirigeant_qualite": "",
        "dirigeant_type": "",
    }

    # Strategy 1: Search by name (with NAF cross-validation)
    entreprise = search_entreprise(business_name, code_postal=zip_code,
                                   gmaps_category=gmaps_category)
    dirigeants = extract_dirigeants(entreprise) if entreprise else []

    # Check if we got a real person
    has_person = any(d.get("type") == "personne physique" for d in dirigeants)

    # Strategy 2: If name search failed or only found personne morale,
    # try scraping the SIREN from the website
    if (not entreprise or not has_person) and website:
        print(f"    Fallback: scraping SIREN from website...")
        siren_from_web = _scrape_siren_from_website(website)
        if siren_from_web:
            print(f"    Found SIREN {siren_from_web} on website")
            web_entreprise, web_dirigeants = _enrich_from_siren(siren_from_web)
            web_has_person = any(
                d.get("type") == "personne physique" for d in web_dirigeants
            )
            # Use website result if it's better
            if web_entreprise and (web_has_person or not entreprise):
                entreprise = web_entreprise
                dirigeants = web_dirigeants

    if not entreprise:
        return empty

    result = {
        "siren": entreprise.get("siren", ""),
        "nom_raison_sociale": entreprise.get("nom_complet", ""),
        "dirigeant_nom": "",
        "dirigeant_prenom": "",
        "dirigeant_qualite": "",
        "dirigeant_type": "",
    }

    if dirigeants:
        # Take the first real director
        d = dirigeants[0]
        result["dirigeant_nom"] = d.get("nom", "")
        result["dirigeant_prenom"] = d.get("prenoms", "")
        result["dirigeant_qualite"] = d.get("qualite", "")
        result["dirigeant_type"] = d.get("type", "")

    return result


def enrich_leads_batch(leads: list[dict]) -> list[dict]:
    """
    Enrich a batch of leads. Each lead dict should have at minimum
    'business_name'. Optionally 'zip_code' for better matching.

    Returns the leads with enrichment fields added.
    """
    total = len(leads)
    for i, lead in enumerate(leads):
        name = lead.get("business_name", "")
        zip_code = lead.get("zip_code", "") or None
        if not name:
            continue

        website = lead.get("website", "") or None
        gmaps_category = lead.get("category", "") or None
        print(f"  [{i+1}/{total}] Enriching: {name}")
        enrichment = enrich_lead(name, zip_code=zip_code, website=website,
                                 gmaps_category=gmaps_category)
        lead.update(enrichment)
        time.sleep(REQUEST_DELAY)

    return leads


def main():
    parser = argparse.ArgumentParser(description="Enrich leads with French dirigeant data")
    parser.add_argument("--name", help="Single business name to look up")
    parser.add_argument("--zip", help="Zip code for better matching")
    parser.add_argument("--file", help="JSON file with leads to enrich")

    args = parser.parse_args()

    if args.name:
        print(f"Looking up: {args.name}")
        result = enrich_lead(args.name, zip_code=args.zip)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.file:
        with open(args.file, "r") as f:
            leads = json.load(f)
        print(f"Enriching {len(leads)} leads...")
        enriched = enrich_leads_batch(leads)
        out_file = args.file.replace(".json", "_enriched.json")
        with open(out_file, "w") as f:
            json.dump(enriched, f, indent=2, ensure_ascii=False)
        print(f"Saved enriched leads to {out_file}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
