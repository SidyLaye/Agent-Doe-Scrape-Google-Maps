from pydantic import BaseModel, Field
from openai import OpenAI

from .config import get_settings


class ProspectMessages(BaseModel):
    email_subject: str
    email_message: str
    whatsapp_message: str
    sms_message: str = Field(max_length=160)


def generate_prospect_messages(prospect: dict) -> ProspectMessages | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    prompt = f"""Rédige trois messages de prospection B2B en français pour ce prospect réel.
Entreprise: {prospect.get('business_name')}. Activité: {prospect.get('category')}.
Décideur: {prospect.get('decision_maker_name') or 'non identifié'}. Fonction: {prospect.get('decision_maker_role') or 'non identifiée'}.
Site: {prospect.get('website')}. Ville: {prospect.get('city')}.
Sois naturel, précis, sobre et personnalisé uniquement à partir de ces faits. N'invente rien.
Email: objet + message court. WhatsApp: conversationnel et bref. SMS: 160 caractères maximum, espaces compris.
Utilise le nom de l'entreprise; utilise le prénom seulement s'il est fourni. Termine par une question simple."""
    response = OpenAI(api_key=settings.openai_api_key).responses.parse(
        model=settings.openai_model, input=prompt, text_format=ProspectMessages
    )
    return response.output_parsed
