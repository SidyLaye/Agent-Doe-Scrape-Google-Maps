# AMBS Outreach

Plateforme générique d'orchestration commerciale multicanale pour tous secteurs.

## Fonctions disponibles

- campagnes email, SMS et WhatsApp ;
- import CSV avec reconnaissance des colonnes françaises et du pipeline existant ;
- déduplication par campagne ;
- personnalisation avec `{first_name}`, `{business_name}`, `{calendar_url}` et `{video_url}` ;
- aperçu avant traitement ;
- traitement plafonné par lot ;
- mode simulation activé par défaut ;
- journal des livraisons, webhooks et liste d'opposition ;
- connecteurs Emelia, iSendPro et AMBS isolés dans le backend.

## PostgreSQL et authentification

AMBS utilise PostgreSQL 17 sur `127.0.0.1:5434`. Les données sont stockées dans
`backend/postgres_data/`, ignoré par Git. Le script `start.ps1` démarre PostgreSQL
avant FastAPI si nécessaire. SQLite n'est plus utilisé par l'application.

Le mot de passe PostgreSQL local se trouve dans `backend/.env.postgres`. Pour un
hébergement, créez ce fichier depuis `backend/.env.postgres.example` dans le
gestionnaire de secrets de la plateforme, sans le commiter.

Le premier administrateur vient de `INITIAL_ADMIN_EMAIL` et
`INITIAL_ADMIN_PASSWORD` dans `backend/.env`. Son mot de passe est haché avec
Argon2 dans PostgreSQL et les sessions de l'interface utilisent des JWT.

## Installation

```powershell
cd backend
python -m pip install -r requirements.txt
Copy-Item .env.example .env

cd ..\frontend
npm install
```

Place Google OAuth files in `backend/secrets/credentials.json` and
`backend/secrets/token.json`. These files and `backend/.env` are ignored by Git.

## Lancement en développement

À la racine :

```powershell
.\start.ps1
```

- Interface : http://localhost:8000
- API et documentation : http://localhost:8000/docs

## Sécurité des envois

`DRY_RUN=true` est la valeur par défaut. Dans ce mode, les messages sont rendus et
journalisés mais aucun fournisseur externe n'est appelé.

Pour un envoi réel, il faut :

1. renseigner les identifiants du fournisseur dans `backend/.env` ;
2. valider son implémentation avec sa documentation et un compte de test ;
3. passer `DRY_RUN=false` ;
4. appeler l'API d'envoi avec `confirm_live=true`.

Le connecteur Emelia requiert encore l'identifiant d'une campagne Emelia configurée.
Le contrat AMBS doit être adapté à sa documentation exacte (`URL`, authentification,
payload et webhooks). Ces deux connecteurs refusent donc explicitement les envois
réels tant qu'ils ne sont pas finalisés.

## Tests

```powershell
cd backend
pytest -q

cd ..\frontend
npm run build
npm run lint
```

