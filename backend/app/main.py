from pathlib import Path
import asyncio
import re
from datetime import datetime, timezone
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db, migrate_sqlite_schema
from .models import Campaign, Contact, Conversation, Delivery, Prospect, ProspectingJob, SequenceStep, Suppression, Template
from .providers import ProviderError, send_message
from .schemas import CampaignCreate, CampaignOut, CampaignUpdate, ContactOut, HandoverUpdate, SendRequest, SequenceStepCreate, SequenceStepOut, SheetImportRequest, SuppressionCreate, TemplateCreate, TemplateOut
from .services import campaign_payload, import_contacts, render
from .google_sheets import list_spreadsheets, read_tab, workbook_metadata
from .auth import create_token, ensure_initial_admin, verify_password, user_from_token
from .schemas import LoginRequest, ProspectingJobCreate, ProspectMessageUpdate, ProspectToCampaign, UserOut
from .prospecting import import_prospect_file, run_prospecting_job
from .ai_messages import generate_message
from .schemas import GenerateMessageRequest, RuntimeModeUpdate, ScheduleCampaignRequest
from .emelia import EmeliaError, pause_campaign as pause_emelia_campaign, start_campaign as start_emelia_campaign, sync_campaign as sync_emelia_campaign


settings = get_settings()
Base.metadata.create_all(engine)
migrate_sqlite_schema()
app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

with SessionLocal() as startup_db:
    ensure_initial_admin(startup_db)


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    public = path in {"/api/health", "/api/auth/login"} or not path.startswith("/api/")
    if public:
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    with SessionLocal() as db:
        user = user_from_token(token, db) if token else None
    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Authentification requise"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "dry_run": settings.dry_run,
        "app": settings.app_name,
        "emelia_configured": bool(settings.emelia_api_key),
        "emelia_sender": settings.emelia_sender_email,
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    from .models import User
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Email ou mot de passe incorrect")
    return {"access_token": create_token(user), "token_type": "bearer", "user": UserOut.model_validate(user)}


@app.get("/api/auth/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    token = request.headers["Authorization"].removeprefix("Bearer ").strip()
    return user_from_token(token, db)


@app.get("/api/config")
def public_config():
    return {
        "dry_run": settings.dry_run,
        "providers": {
            "emelia": bool(settings.emelia_api_key),
            "isendpro": bool(settings.isendpro_key_id),
            "ambs": bool(settings.ambs_api_key and settings.ambs_api_url),
            "openai": bool(settings.openai_api_key),
        },
    }


@app.patch("/api/config/mode")
def update_runtime_mode(payload: RuntimeModeUpdate):
    if not payload.dry_run and not payload.confirm_live:
        raise HTTPException(409, "Une confirmation explicite est obligatoire pour activer les envois réels")
    env_path = Path(__file__).resolve().parents[1] / ".env"
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    value = "true" if payload.dry_run else "false"
    if re.search(r"(?m)^DRY_RUN=.*$", content):
        content = re.sub(r"(?m)^DRY_RUN=.*$", f"DRY_RUN={value}", content)
    else:
        content = f"{content.rstrip()}\nDRY_RUN={value}\n"
    env_path.write_text(content, encoding="utf-8")
    settings.dry_run = payload.dry_run
    return {"dry_run": settings.dry_run}


@app.get("/api/google-sheets")
def google_sheets_files():
    try: return {"connected": True, "files": list_spreadsheets()}
    except Exception as exc: raise HTTPException(502, f"Connexion Google Sheets impossible : {exc}") from exc


@app.get("/api/google-sheets/metadata")
def google_sheet_metadata(spreadsheet: str):
    try: return workbook_metadata(spreadsheet)
    except Exception as exc: raise HTTPException(502, f"Lecture du classeur impossible : {exc}") from exc


@app.get("/api/google-sheets/preview")
def google_sheet_preview(spreadsheet: str, sheet_name: str, limit: int = 100):
    try: return read_tab(spreadsheet, sheet_name, min(max(limit, 1), 200))
    except Exception as exc: raise HTTPException(502, f"Lecture de l'onglet impossible : {exc}") from exc


@app.post("/api/campaigns/{campaign_id}/contacts/import-sheet")
def import_google_sheet(campaign_id: int, payload: SheetImportRequest, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    try:
        data = read_tab(payload.spreadsheet, payload.sheet_name, 5000)
        import csv, io
        stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=data["headers"]); writer.writeheader(); writer.writerows(data["rows"])
        result = import_contacts(db, campaign, stream.getvalue().encode("utf-8-sig"))
        return {**result, "source": data["spreadsheet_name"], "sheet_name": data["sheet_name"]}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(502, f"Import Google Sheets impossible : {exc}") from exc


@app.get("/api/campaigns", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return [campaign_payload(db, item) for item in db.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all()]


@app.post("/api/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    if payload.channel not in {"email", "sms", "whatsapp"}:
        raise HTTPException(422, "Canal invalide")
    campaign = Campaign(**payload.model_dump())
    db.add(campaign); db.commit(); db.refresh(campaign)
    return campaign_payload(db, campaign)


def get_campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign: raise HTTPException(404, "Campagne introuvable")
    return campaign


@app.get("/api/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return campaign_payload(db, get_campaign_or_404(db, campaign_id))


@app.patch("/api/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(campaign, key, value)
    if campaign.channel == "email" and campaign.provider == "emelia" and settings.emelia_api_key and settings.database_url.startswith("postgresql"):
        try: sync_emelia_campaign(settings, campaign)
        except Exception as exc: raise HTTPException(502, f"Synchronisation Emelia impossible : {exc}") from exc
    db.commit(); db.refresh(campaign)
    return campaign_payload(db, campaign)


@app.post("/api/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.channel != "email" or campaign.provider != "emelia":
        raise HTTPException(422, "La pause distante est disponible pour les campagnes Emelia")
    try: pause_emelia_campaign(settings, campaign)
    except EmeliaError as exc: raise HTTPException(502, str(exc)) from exc
    campaign.status = "paused"; db.commit()
    return campaign_payload(db, campaign)


@app.post("/api/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.channel != "email" or campaign.provider != "emelia":
        raise HTTPException(422, "La reprise distante est disponible pour les campagnes Emelia")
    try: start_emelia_campaign(settings, campaign)
    except EmeliaError as exc: raise HTTPException(502, str(exc)) from exc
    campaign.status = "running"; db.commit()
    return campaign_payload(db, campaign)


@app.post("/api/campaigns/{campaign_id}/contacts/import")
async def upload_contacts(campaign_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    if not (file.filename or "").lower().endswith(".csv"): raise HTTPException(422, "Un fichier CSV est requis")
    try: return import_contacts(db, campaign, await file.read())
    except (UnicodeDecodeError, ValueError) as exc: raise HTTPException(422, f"CSV invalide: {exc}") from exc


@app.get("/api/campaigns/{campaign_id}/contacts", response_model=list[ContactOut])
def list_contacts(campaign_id: int, min_score: int = 0, status: str | None = None, tag: str | None = None, db: Session = Depends(get_db)):
    get_campaign_or_404(db, campaign_id)
    query = select(Contact).where(Contact.campaign_id == campaign_id, Contact.score >= min_score)
    if status: query = query.where(Contact.status == status)
    if tag: query = query.where(Contact.tags.contains(tag))
    return db.scalars(query.order_by(Contact.score.desc(), Contact.id.desc())).all()


@app.get("/api/campaigns/{campaign_id}/sequence", response_model=list[SequenceStepOut])
def sequence(campaign_id: int, db: Session = Depends(get_db)):
    get_campaign_or_404(db, campaign_id)
    return db.scalars(select(SequenceStep).where(SequenceStep.campaign_id == campaign_id).order_by(SequenceStep.position)).all()


@app.post("/api/campaigns/{campaign_id}/sequence", response_model=SequenceStepOut, status_code=201)
def add_sequence_step(campaign_id: int, payload: SequenceStepCreate, db: Session = Depends(get_db)):
    get_campaign_or_404(db, campaign_id)
    position = (db.scalar(select(func.max(SequenceStep.position)).where(SequenceStep.campaign_id == campaign_id)) or 0) + 1
    step = SequenceStep(campaign_id=campaign_id, position=position, **payload.model_dump())
    db.add(step); db.commit(); db.refresh(step)
    return step


@app.delete("/api/campaigns/{campaign_id}/sequence/{step_id}", status_code=204)
def delete_sequence_step(campaign_id: int, step_id: int, db: Session = Depends(get_db)):
    step = db.scalar(select(SequenceStep).where(SequenceStep.id == step_id, SequenceStep.campaign_id == campaign_id))
    if not step: raise HTTPException(404, "Étape introuvable")
    db.delete(step); db.commit()


@app.get("/api/templates", response_model=list[TemplateOut])
def templates(db: Session = Depends(get_db)):
    return db.scalars(select(Template).order_by(Template.created_at.desc())).all()


@app.post("/api/templates", response_model=TemplateOut, status_code=201)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    template = Template(**payload.model_dump()); db.add(template); db.commit(); db.refresh(template); return template


@app.get("/api/analytics")
def analytics(db: Session = Depends(get_db)):
    statuses = dict(db.execute(select(Delivery.status, func.count(Delivery.id)).group_by(Delivery.status)).all())
    channels = dict(db.execute(select(Delivery.channel, func.count(Delivery.id)).group_by(Delivery.channel)).all())
    return {"campaigns": db.scalar(select(func.count(Campaign.id))) or 0, "contacts": db.scalar(select(func.count(Contact.id))) or 0, "deliveries": sum(statuses.values()), "by_status": statuses, "by_channel": channels, "opted_out": db.scalar(select(func.count(Contact.id)).where(Contact.opted_out.is_(True))) or 0}


@app.get("/api/contacts", response_model=list[ContactOut])
def all_contacts(search: str = "", limit: int = 200, db: Session = Depends(get_db)):
    query = select(Contact)
    if search:
        term = f"%{search}%"
        query = query.where((Contact.business_name.ilike(term)) | (Contact.first_name.ilike(term)) | (Contact.last_name.ilike(term)) | (Contact.email.ilike(term)))
    return db.scalars(query.order_by(Contact.score.desc(), Contact.id.desc()).limit(min(limit, 500))).all()


@app.post("/api/prospecting/jobs", status_code=202)
def create_prospecting_job(payload: ProspectingJobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    job = ProspectingJob(query=payload.query, location=payload.location, requested_limit=payload.limit)
    db.add(job); db.commit(); db.refresh(job)
    background.add_task(run_prospecting_job, job.id)
    return job


@app.post("/api/prospects/import")
async def import_prospects(file: UploadFile = File(...)):
    try: return import_prospect_file(file.filename or "", await file.read())
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post("/api/ai/generate-message")
def ai_generate_message(payload: GenerateMessageRequest):
    try: return generate_message(payload).model_dump()
    except Exception as exc: raise HTTPException(502, f"Génération OpenAI impossible : {exc}") from exc


@app.get("/api/prospecting/jobs")
def prospecting_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(ProspectingJob).order_by(ProspectingJob.created_at.desc()).limit(100)).all()


@app.get("/api/prospects")
def prospects(search: str = "", status: str = "", quality: str = "qualified", min_quality: int = 70, has_email: bool | None = None, job_id: int | None = None, limit: int = 500, db: Session = Depends(get_db)):
    query = select(Prospect)
    if quality: query = query.where(Prospect.validation_status == quality)
    if min_quality: query = query.where(Prospect.quality_score >= min_quality)
    query = query.where(Prospect.email != "", Prospect.phone != "")
    if search:
        term = f"%{search}%"; query = query.where((Prospect.business_name.ilike(term)) | (Prospect.city.ilike(term)) | (Prospect.category.ilike(term)) | (Prospect.email.ilike(term)))
    if status: query = query.where(Prospect.status == status)
    if has_email is True: query = query.where(Prospect.email != "")
    if has_email is False: query = query.where(Prospect.email == "")
    if job_id: query = query.where(Prospect.job_id == job_id)
    rows = db.scalars(query.order_by(Prospect.score.desc(), Prospect.created_at.desc()).limit(min(limit, 1000))).all()
    contacts = db.execute(select(Contact, Campaign).join(Campaign, Campaign.id == Contact.campaign_id)).all()
    deliveries = db.scalars(select(Delivery).order_by(Delivery.created_at.desc())).all()
    deliveries_by_contact: dict[int, list[Delivery]] = {}
    for delivery in deliveries:
        deliveries_by_contact.setdefault(delivery.contact_id, []).append(delivery)

    def digits(value: str) -> str:
        return re.sub(r"\D", "", value or "")

    result = []
    for prospect in rows:
        matched = []
        for contact, campaign in contacts:
            same_email = bool(prospect.email and contact.email and prospect.email.casefold() == contact.email.casefold())
            same_phone = bool(digits(prospect.phone) and digits(prospect.phone) == digits(contact.phone))
            same_company = prospect.business_name.strip().casefold() == contact.business_name.strip().casefold()
            if same_email or same_phone or (same_company and (prospect.email or prospect.phone)):
                matched.append((contact, campaign))

        history = []
        for contact, campaign in matched:
            contact_deliveries = deliveries_by_contact.get(contact.id, [])
            last = contact_deliveries[0] if contact_deliveries else None
            history.append({
                "id": campaign.id,
                "name": campaign.name,
                "channel": campaign.channel,
                "contact_status": contact.status,
                "delivery_status": last.status if last else "",
                "last_contacted_at": last.created_at if last else None,
            })

        all_deliveries = [delivery for contact, _ in matched for delivery in deliveries_by_contact.get(contact.id, [])]
        latest = max(all_deliveries, key=lambda item: item.created_at) if all_deliveries else None
        if any(contact.opted_out for contact, _ in matched):
            crm_status = "opted_out"
        elif any(item.status in {"sent", "delivered", "queued", "simulated"} for item in all_deliveries):
            crm_status = "contacted"
        elif any(item.status == "failed" for item in all_deliveries):
            crm_status = "failed"
        elif matched:
            crm_status = "targeted"
        else:
            crm_status = "new"

        item = {column.name: getattr(prospect, column.name) for column in Prospect.__table__.columns}
        item.update({
            "crm_status": crm_status,
            "campaigns": history,
            "campaign_count": len(history),
            "last_contacted_at": latest.created_at if latest else None,
        })
        result.append(item)
    return result


@app.post("/api/prospects/add-to-campaign")
def prospects_to_campaign(payload: ProspectToCampaign, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, payload.campaign_id)
    query = select(Prospect)
    if payload.prospect_ids: query = query.where(Prospect.id.in_(payload.prospect_ids))
    prospects = db.scalars(query).all()
    added = duplicates = invalid = 0
    import hashlib
    for prospect in prospects:
        destination = prospect.email if campaign.channel == "email" else prospect.phone
        if not destination: invalid += 1; continue
        key = hashlib.sha256(f"{destination}|{prospect.business_name}".lower().encode()).hexdigest()
        if db.scalar(select(Contact.id).where(Contact.campaign_id == campaign.id, Contact.dedupe_key == key)): duplicates += 1; continue
        name = prospect.decision_maker_name.split(maxsplit=1) if prospect.decision_maker_name else []
        db.add(Contact(campaign_id=campaign.id, business_name=prospect.business_name, first_name=name[0] if name else "", last_name=name[1] if len(name)>1 else "", role=prospect.decision_maker_role, email=prospect.email, phone=re.sub(r"\D", "", prospect.phone), city=prospect.city, website=prospect.website, source=prospect.google_maps_url, score=prospect.score, email_subject=prospect.email_subject, email_message=prospect.email_message, whatsapp_message=prospect.whatsapp_message, sms_message=prospect.sms_message, dedupe_key=key))
        prospect.status = "assigned"; added += 1
    db.commit(); return {"added": added, "duplicates": duplicates, "invalid": invalid}


@app.patch("/api/prospects/{prospect_id}/messages")
def update_prospect_messages(prospect_id: int, payload: ProspectMessageUpdate, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect: raise HTTPException(404, "Prospect introuvable")
    for field, value in payload.model_dump().items(): setattr(prospect, field, value.strip())
    db.commit(); db.refresh(prospect)
    return {column.name: getattr(prospect, column.name) for column in Prospect.__table__.columns}


@app.get("/api/deliveries")
def deliveries(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.execute(select(Delivery, Contact, Campaign).join(Contact, Contact.id == Delivery.contact_id).join(Campaign, Campaign.id == Delivery.campaign_id).order_by(Delivery.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": delivery.id, "campaign": campaign.name, "contact": f"{contact.first_name} {contact.last_name}".strip(), "business_name": contact.business_name, "channel": delivery.channel, "provider": delivery.provider, "status": delivery.status, "error": delivery.error, "created_at": delivery.created_at} for delivery, contact, campaign in rows]


@app.get("/api/suppressions")
def suppressions(db: Session = Depends(get_db)):
    return db.scalars(select(Suppression).order_by(Suppression.created_at.desc())).all()


@app.get("/api/conversations")
def conversations(db: Session = Depends(get_db)):
    rows = db.execute(select(Conversation, Contact).join(Contact, Contact.id == Conversation.contact_id).order_by(Conversation.updated_at.desc())).all()
    return [{"id": conversation.id, "contact_id": contact.id, "contact": f"{contact.first_name} {contact.last_name}".strip(), "business_name": contact.business_name, "channel": conversation.channel, "state": conversation.state, "paused": conversation.paused, "last_message": conversation.last_message, "updated_at": conversation.updated_at} for conversation, contact in rows]


@app.patch("/api/conversations/{contact_id}/handover")
def handover(contact_id: int, payload: HandoverUpdate, db: Session = Depends(get_db)):
    if not db.get(Contact, contact_id): raise HTTPException(404, "Contact introuvable")
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    if not conversation: conversation = Conversation(contact_id=contact_id); db.add(conversation)
    conversation.paused = payload.paused
    db.commit(); db.refresh(conversation)
    return {"contact_id": contact_id, "paused": conversation.paused}


@app.get("/api/campaigns/{campaign_id}/preview")
def preview(campaign_id: int, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    contact = db.scalar(select(Contact).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False)))
    if not contact: raise HTTPException(404, "Aucun contact disponible")
    subject, message = personalized_content(campaign, contact)
    return {"contact": ContactOut.model_validate(contact), "subject": subject, "message": message}


def personalized_content(campaign: Campaign, contact: Contact) -> tuple[str, str]:
    """Resolve the copy approved on the prospect before using a legacy fallback."""
    if campaign.channel == "email":
        subject = contact.email_subject or campaign.subject
        message = contact.email_message or campaign.message
    elif campaign.channel == "whatsapp":
        subject, message = "", contact.whatsapp_message or campaign.message
    else:
        subject, message = "", contact.sms_message or campaign.message
    return render(subject, campaign, contact), render(message, campaign, contact)


async def process_campaign(campaign_id: int, limit: int, db: Session) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.channel == "sms" and len(campaign.message) > 160:
        raise HTTPException(422, f"Le SMS contient {len(campaign.message)} caractères. Maximum autorisé : 160.")
    contacts = db.scalars(select(Contact).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False), Contact.status == "ready").limit(limit)).all()
    summary = {"processed": 0, "simulated": 0, "queued": 0, "skipped": 0, "failed": 0}
    for contact in contacts:
        subject, message = personalized_content(campaign, contact)
        if campaign.channel == "sms" and len(message) > 160:
            summary["skipped"] += 1
            summary["processed"] += 1
            db.add(Delivery(campaign_id=campaign.id, contact_id=contact.id, channel=campaign.channel, provider=campaign.provider, status="skipped", error=f"SMS trop long : {len(message)}/160", rendered_message=message))
            continue
        try:
            result = await send_message(settings, campaign.provider, campaign.channel, contact, subject, message, campaign)
        except (ProviderError, Exception) as exc:
            result_status, external_id, error = "failed", "", str(exc)
        else:
            result_status, external_id, error = result.status, result.external_id, result.error
        db.add(Delivery(campaign_id=campaign.id, contact_id=contact.id, channel=campaign.channel, provider=campaign.provider, status=result_status, external_id=external_id, error=error, rendered_message=message))
        if result_status == "queued": contact.status = result_status
        summary[result_status if result_status in summary else "failed"] += 1
        summary["processed"] += 1
        if summary["processed"] % 10 == 0:
            db.commit()
            if not settings.dry_run and campaign.channel in {"sms", "whatsapp"}:
                await asyncio.sleep(1)
    if not settings.dry_run and campaign.channel == "email" and campaign.provider == "emelia" and summary["queued"]:
        try: start_emelia_campaign(settings, campaign)
        except Exception as exc:
            summary["failed"] += 1
            campaign.external_status = "ERROR"
            campaign.status = "failed"
            db.commit()
            raise HTTPException(502, f"Contacts synchronisés mais démarrage Emelia impossible : {exc}") from exc
    summary["remaining"] = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False), Contact.status == "ready")) or 0
    if settings.dry_run:
        campaign.status = "simulated"
    elif campaign.channel == "email" and campaign.provider == "emelia" and campaign.external_status == "RUNNING":
        campaign.status = "running"
    elif summary["failed"] and not summary["queued"]:
        campaign.status = "failed"
    else:
        campaign.status = "completed" if not summary["remaining"] else "running"
    db.commit()
    return summary


@app.post("/api/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: int, request: SendRequest, db: Session = Depends(get_db)):
    if not settings.dry_run and not request.confirm_live: raise HTTPException(409, "confirm_live=true est obligatoire pour un envoi réel")
    return await process_campaign(campaign_id, request.limit, db)


@app.post("/api/campaigns/{campaign_id}/schedule")
def schedule_campaign(campaign_id: int, payload: ScheduleCampaignRequest, db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    scheduled_at = payload.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    if scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(422, "La date de programmation doit être dans le futur")
    if not settings.dry_run and not payload.confirm_live:
        raise HTTPException(409, "Une confirmation explicite est obligatoire pour programmer un envoi réel")
    if campaign.channel == "sms" and len(campaign.message) > 160:
        raise HTTPException(422, f"Le SMS contient {len(campaign.message)} caractères. Maximum : 160.")
    campaign.scheduled_at = scheduled_at
    campaign.status = "scheduled"
    db.commit(); db.refresh(campaign)
    return campaign_payload(db, campaign)


async def scheduled_campaign_worker():
    while True:
        try:
            with SessionLocal() as db:
                due_ids = list(db.scalars(select(Campaign.id).where(Campaign.status == "scheduled", Campaign.scheduled_at <= datetime.now(timezone.utc))).all())
            for campaign_id in due_ids:
                with SessionLocal() as db:
                    campaign = db.get(Campaign, campaign_id)
                    if not campaign or campaign.status != "scheduled": continue
                    campaign.status = "running"; db.commit()
                    try: await process_campaign(campaign_id, 500, db)
                    except Exception:
                        campaign.status = "failed"; db.commit()
        finally:
            await asyncio.sleep(20)


@app.on_event("startup")
async def start_scheduled_campaign_worker():
    asyncio.create_task(scheduled_campaign_worker())


@app.post("/api/suppressions", status_code=201)
def suppress(payload: SuppressionCreate, db: Session = Depends(get_db)):
    value = payload.value.strip().lower()
    existing = db.scalar(select(Suppression).where(Suppression.value == value))
    if not existing: db.add(Suppression(value=value, reason=payload.reason))
    for contact in db.scalars(select(Contact).where((Contact.email == value) | (Contact.phone == value))).all(): contact.opted_out = True
    db.commit()
    return {"value": value, "suppressed": True}


@app.post("/api/webhooks/{provider}")
async def provider_webhook(provider: str, payload: dict, db: Session = Depends(get_db)):
    external_id = str(payload.get("id") or payload.get("message_id") or "")
    status = str(payload.get("status") or "received")
    if external_id:
        delivery = db.scalar(select(Delivery).where(Delivery.external_id == external_id))
        if delivery: delivery.status = status; db.commit()
    return {"accepted": True, "provider": provider}


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        candidate = frontend_dist / path
        return FileResponse(candidate if candidate.is_file() else frontend_dist / "index.html")
