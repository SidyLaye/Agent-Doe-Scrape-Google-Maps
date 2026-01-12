# GMaps Lead Scraper Agent

Pipeline automatique : Google Maps -> Enrichissement Dirigeant -> Google Sheet.

Donne ce dossier a n'importe quelle IA (Claude, Gemini, GPT, Cursor...) et elle saura tout faire.

---

## Ce que fait l'agent

1. **Scrape Google Maps** via Apify (50 resultats en ~30s)
2. **Enrichit chaque entreprise** avec les donnees du dirigeant (SIREN, nom, prenom, qualite) via l'API gouvernementale gratuite
3. **Exporte dans une Google Sheet** automatiquement

**38 secteurs** supportes : auto, restaurant, immobilier, beaute, BTP, informatique, sante, pharmacie, etc.

**Taux d'enrichissement** : ~85-90% pour les entreprises francaises.

---

## Setup (5 min)

### 1. Python + dependances

```bash
# Python 3.11+ requis
pip install -r requirements.txt

# Pour le scraping SIREN sur les sites web (optionnel mais recommande)
python -m playwright install chromium
```

### 2. Cle API Apify

1. Creer un compte sur [apify.com](https://apify.com/)
2. Recuperer votre API Token dans Settings > Integrations
3. Copier `.env.example` en `.env` et remplir :

```env
APIFY_API_TOKEN=votre_cle_ici
GOOGLE_APPLICATION_CREDENTIALS=credentials.json
```

### 3. Google Sheets (OAuth)

Suivez le tuto en images dans `tuto credentials/` :

1. Aller sur [console.cloud.google.com](https://console.cloud.google.com/)
2. Creer un projet
3. Activer **Google Sheets API** + **Google Drive API**
4. Configurer l'ecran de consentement OAuth (External)
5. Creer des identifiants OAuth (type **Desktop App**)
6. Telecharger le JSON, le renommer `credentials.json`
7. Le placer a la racine du projet **ET** dans `execution/`
8. Ajouter votre email comme utilisateur de test

> Au premier lancement, un navigateur s'ouvre pour autoriser l'acces. Cliquez "Autoriser". Un fichier `token.json` est cree automatiquement.

### 4. Copier les credentials dans execution/

```bash
cp .env execution/.env
cp credentials.json execution/credentials.json
# token.json sera cree automatiquement au premier lancement
```

---

## Utilisation

### Via l'IA (methode recommandee)

Ouvrez le projet dans Cursor, Claude Code, Windsurf, ou n'importe quel IDE avec IA et demandez :

> *"Cherche 50 garages automobiles en Ile-de-France"*
>
> *"Recupere 20 agences immobilieres a Lyon"*
>
> *"Scrape 30 restaurants a Bordeaux"*

L'IA lit les instructions dans `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, comprend l'architecture, et execute le bon script.

### Via la ligne de commande (mode manuel)

```bash
cd execution

# 50 garages en Ile-de-France
python gmaps_lead_pipeline.py --search "garage automobile" --location "Ile-de-France" --limit 50

# 20 agences immobilieres a Lyon
python gmaps_lead_pipeline.py --search "agences immobilieres" --location "Lyon" --limit 20

# Enrichir une entreprise specifique
python enrich_dirigeants.py --name "Laforet Lyon" --zip 69002

# Nettoyer les noms dans une sheet existante (CAPS -> Title Case)
python clean_sheet_names.py
```

---

## Structure du projet

```
.
├── CLAUDE.md / AGENTS.md / GEMINI.md   # Instructions IA (identiques)
├── README.md                            # Ce fichier
├── requirements.txt                     # Dependances Python
├── .env.example                         # Template de config
├── .env                                 # Config reelle (pas commite)
├── credentials.json                     # OAuth Google (pas commite)
├── token.json                           # Token auto-genere (pas commite)
│
├── directives/                          # SOPs Markdown
│   └── scrape_google_maps.md            # Directive principale
│
├── execution/                           # Scripts Python
│   ├── gmaps_lead_pipeline.py           # Pipeline principal (orchestrateur)
│   ├── scrape_google_maps.py            # Scraping Google Maps via Apify
│   ├── enrich_dirigeants.py             # Enrichissement dirigeant (API gouv)
│   ├── enrich_linkedin.py              # Utilitaires nettoyage noms
│   └── clean_sheet_names.py             # Nettoyage noms dans sheet existante
│
├── tuto credentials/                    # Captures d'ecran setup Google Cloud
│   ├── 1. Create Project.png
│   ├── ...
│   └── 15. Add test user.png
│
└── .tmp/                                # Fichiers temporaires (auto-genere)
```

---

## Colonnes du Google Sheet

| Colonne | Description |
|---|---|
| `lead_id` | ID unique (hash nom+adresse) |
| `scraped_at` | Date/heure du scraping |
| `search_query` | Recherche effectuee |
| `business_name` | Nom commercial (Google Maps) |
| `category` | Categorie Google Maps |
| `address` | Adresse complete |
| `city` / `state` / `zip_code` / `country` | Decomposition adresse |
| `phone` | Telephone |
| `website` | Site web |
| `google_maps_url` | Lien Google Maps |
| `place_id` | ID Google Places |
| `rating` / `review_count` | Note et nombre d'avis |
| `price_level` | Niveau de prix |
| `siren` | Numero SIREN |
| `nom_raison_sociale` | Raison sociale officielle |
| `dirigeant_nom` | Nom du dirigeant |
| `dirigeant_prenom` | Prenom du dirigeant |
| `dirigeant_qualite` | Role (President, Gerant...) |
| `dirigeant_type` | personne physique / morale |

---

## Notes techniques

- **Geolocation** : Apify scrape depuis les US par defaut. Le script geocode automatiquement toute localisation francaise
- **Anti-doublon** : Le pipeline ne rajoute jamais le meme business deux fois (base sur nom + adresse)
- **NAF Validation** : Chaque resultat est croise avec le code NAF/APE pour eviter les faux positifs (un garage ne matchera pas un salon de coiffure)
- **Nettoyage noms** : Les noms de dirigeants sont automatiquement mis en forme (DUPONT JEAN-PIERRE ANDRE -> Jean-Pierre Dupont)
- **Playwright** : Utilise comme fallback pour scraper le SIREN sur les sites en JavaScript. Optionnel mais ameliore le taux d'enrichissement de ~5%
