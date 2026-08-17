from pydantic import BaseModel
from openai import OpenAI
from .config import get_settings


class GeneratedMessage(BaseModel):
    subject: str
    text: str
    html: str
    rationale: str


def generate_message(payload) -> GeneratedMessage:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY n'est pas configurée dans backend/.env")
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = f"""Crée un message de prospection B2B en français.
Canal: {payload.channel}. Secteur: {payload.sector or 'générique'}. Audience: {payload.audience or 'décideurs'}.
Objectif: {payload.objective}. Offre: {payload.offer}. Ton: {payload.tone}.
Calendrier: {payload.calendar_url}. Vidéo: {payload.video_url}.
Instructions: {payload.extra_instructions}.
Le texte doit sembler écrit individuellement: phrases naturelles, précises, sobres, sans superlatifs ni jargon IA.
N'invente aucun fait sur le prospect. Utilise les variables {{{{first_name}}}}, {{{{business_name}}}}, {{{{role}}}}, {{{{calendar_url}}}} et {{{{video_url}}}} si pertinentes.
Pour email, fournis un HTML responsive simple, sans scripts ni CSS externe. Pour SMS, le champ text doit impérativement rester à 160 caractères maximum, espaces et lien inclus. Pour WhatsApp, reste bref et conversationnel.
Ne prétends jamais être humain et n'emploie pas de manipulation trompeuse."""
    response = client.responses.parse(model=settings.openai_model, input=prompt, text_format=GeneratedMessage)
    if not response.output_parsed:
        raise RuntimeError("OpenAI n'a pas retourné de message exploitable")
    if payload.channel == "sms" and len(response.output_parsed.text) > 160:
        raise RuntimeError(f"Le brouillon SMS généré contient {len(response.output_parsed.text)} caractères au lieu de 160 maximum")
    return response.output_parsed
