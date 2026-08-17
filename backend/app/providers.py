from dataclasses import dataclass
import httpx
from .config import Settings


@dataclass
class SendResult:
    status: str
    external_id: str = ""
    error: str = ""


class ProviderError(RuntimeError):
    pass


def destination_for(channel: str, contact) -> str:
    return contact.email if channel == "email" else contact.phone


async def send_message(settings: Settings, provider: str, channel: str, contact, subject: str, message: str, campaign=None) -> SendResult:
    destination = destination_for(channel, contact)
    if not destination:
        return SendResult("skipped", error=f"missing {channel} destination")
    if settings.dry_run:
        return SendResult("simulated", external_id=f"dry-{contact.id}")
    if provider == "emelia" and channel == "email":
        return await _send_emelia(settings, campaign, contact, subject, message)
    if provider == "isendpro" and channel == "sms":
        return await _send_isendpro(settings, destination, message)
    if provider == "ambs" and channel == "whatsapp":
        return await _send_ambs(settings, destination, message)
    raise ProviderError(f"Unsupported provider/channel: {provider}/{channel}")


async def _send_emelia(settings: Settings, campaign, contact, subject: str, message: str) -> SendResult:
    if not settings.emelia_api_key:
        raise ProviderError("EMELIA_API_KEY is missing")
    if campaign is None:
        raise ProviderError("Emelia campaign is missing")
    from .emelia import add_contact
    try:
        external_id = add_contact(settings, campaign, contact)
    except Exception as exc:
        raise ProviderError(str(exc)) from exc
    return SendResult("queued", external_id=external_id)


async def _send_isendpro(settings: Settings, destination: str, message: str) -> SendResult:
    if not settings.isendpro_key_id:
        raise ProviderError("ISENDPRO_KEY_ID is missing")
    destination = "+" + destination.lstrip("+")
    if not destination[1:].isdigit() or len(destination) < 9:
        raise ProviderError("Invalid international phone number")
    payload = {"keyid": settings.isendpro_key_id, "sms": message, "num": destination}
    endpoint = settings.isendpro_api_url.rstrip("/")
    if not endpoint.endswith("/sms"):
        endpoint += "/sms"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
    state = data.get("etat", {}).get("etat", {}) if isinstance(data, dict) else {}
    if isinstance(state, list):
        state = state[0] if state else {}
    code = str(state.get("code", ""))
    if code != "0":
        raise ProviderError(f"iSendPro refused the SMS (code {code or 'unknown'}): {state.get('message', 'unknown error')}")
    return SendResult("queued", external_id=str(state.get("tel") or response.headers.get("x-request-id", "")))


async def _send_ambs(settings: Settings, destination: str, message: str) -> SendResult:
    if not settings.ambs_api_key or not settings.ambs_api_url:
        raise ProviderError("AMBS_API_KEY or AMBS_API_URL is missing")
    headers = {"Authorization": f"Bearer {settings.ambs_api_key}"}
    payload = {"to": destination, "message": message, "sender_id": settings.ambs_sender_id}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(settings.ambs_api_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return SendResult("queued", external_id=str(data.get("id", "")))
