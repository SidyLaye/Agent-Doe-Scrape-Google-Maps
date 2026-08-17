import httpx

from .config import Settings


class EmeliaError(RuntimeError):
    pass


def _graphql(settings: Settings, query: str, variables: dict | None = None) -> dict:
    response = httpx.post(
        settings.emelia_api_url,
        headers={"Authorization": settings.emelia_api_key},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise EmeliaError(payload["errors"][0].get("message", "Erreur Emelia"))
    return payload.get("data") or {}


def sender_provider(settings: Settings) -> dict:
    data = _graphql(settings, "query { providers { _id senderEmail senderName } }")
    provider = next((item for item in data.get("providers", []) if item.get("senderEmail", "").casefold() == settings.emelia_sender_email.casefold()), None)
    if not provider:
        raise EmeliaError(f"Boîte Emelia introuvable : {settings.emelia_sender_email}")
    return provider


def _remote_campaign_name(campaign) -> str:
    """Use a stable account-wide unique name; Emelia rejects duplicate names."""
    return f"AMBS · {campaign.name} · #{campaign.id}"


def find_campaign_by_name(settings: Settings, name: str) -> dict | None:
    data = _graphql(
        settings,
        "query($options:JSON){all_campaigns(options:$options){_id name status}}",
        {},
    )
    return next(
        (item for item in data.get("all_campaigns", []) if item.get("name", "").strip().casefold() == name.strip().casefold()),
        None,
    )


def sync_campaign(settings: Settings, campaign) -> str:
    if not settings.emelia_api_key:
        raise EmeliaError("EMELIA_API_KEY absente")
    provider = sender_provider(settings)
    external_id = campaign.external_id
    remote_name = _remote_campaign_name(campaign)
    if not external_id:
        existing = find_campaign_by_name(settings, remote_name)
        if existing:
            external_id = existing["_id"]
        else:
            data = _graphql(
                settings,
                "mutation($name:String!){createCampaign(name:$name){_id status}}",
                {"name": remote_name},
            )
            external_id = data["createCampaign"]["_id"]
    # Keep the association even if a later settings/contact call fails.
    campaign.external_id = external_id
    version = {
        "subject": campaign.subject,
        "message": campaign.message,
        "rawHtml": campaign.content_type == "html",
        "disabled": False,
        "attachments": [],
    }
    settings_data = {
        "provider": {"id": provider["_id"]},
        "steps": [{"delay": {"amount": 0, "unit": "DAYS"}, "versions": [version]}],
    }
    data = _graphql(
        settings,
        "mutation($id:ID!,$data:JSON!){updateCampaignSettings(id:$id,data:$data){_id status}}",
        {"id": external_id, "data": settings_data},
    )
    campaign.external_status = data["updateCampaignSettings"].get("status", "DRAFT")
    campaign.sender_email = settings.emelia_sender_email
    return external_id


def add_contact(settings: Settings, campaign, contact) -> str:
    if not campaign.external_id:
        sync_campaign(settings, campaign)
    payload = {
        "email": contact.email,
        "firstName": contact.first_name,
        "lastName": contact.last_name,
        "company": contact.business_name,
    }
    data = _graphql(
        settings,
        "mutation($id:ID!,$contact:JSON!){addContactToCampaignHook(id:$id,contact:$contact)}",
        {"id": campaign.external_id, "contact": payload},
    )
    return str(data.get("addContactToCampaignHook") or "")


def start_campaign(settings: Settings, campaign) -> None:
    sync_campaign(settings, campaign)
    data = _graphql(settings, "mutation($id:ID!){startCampaign(id:$id)}", {"id": campaign.external_id})
    if data.get("startCampaign") is not True:
        raise EmeliaError("Emelia n'a pas confirmé le démarrage de la campagne")
    campaign.external_status = "RUNNING"


def pause_campaign(settings: Settings, campaign) -> None:
    if not campaign.external_id:
        raise EmeliaError("Cette campagne n'est pas encore synchronisée avec Emelia")
    _graphql(settings, "mutation($id:ID!){pauseCampaign(id:$id)}", {"id": campaign.external_id})
    campaign.external_status = "PAUSED"
