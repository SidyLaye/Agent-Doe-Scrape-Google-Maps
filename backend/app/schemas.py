from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    channel: str = "email"
    provider: str = "emelia"
    subject: str = ""
    message: str
    calendar_url: str = ""
    video_url: str = ""
    sector: str = ""
    objective: str = "book_meeting"
    tags: str = ""
    content_type: str = "text"
    scheduled_at: datetime | None = None
    time_zone: str = "Europe/Paris"

    @model_validator(mode="after")
    def validate_channel_content(self):
        if self.channel == "sms" and len(self.message) > 160:
            raise ValueError("Un SMS ne peut pas dépasser 160 caractères")
        return self


class CampaignUpdate(BaseModel):
    name: str | None = None
    channel: str | None = None
    provider: str | None = None
    subject: str | None = None
    message: str | None = None
    calendar_url: str | None = None
    video_url: str | None = None
    sector: str | None = None
    objective: str | None = None
    tags: str | None = None
    content_type: str | None = None
    scheduled_at: datetime | None = None
    time_zone: str | None = None

    @model_validator(mode="after")
    def validate_channel_content(self):
        if self.channel == "sms" and self.message is not None and len(self.message) > 160:
            raise ValueError("Un SMS ne peut pas dépasser 160 caractères")
        return self


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    channel: str
    provider: str
    status: str
    subject: str
    message: str
    calendar_url: str
    video_url: str
    sector: str
    objective: str
    tags: str
    content_type: str
    external_id: str = ""
    external_status: str = ""
    sender_email: str = ""
    scheduled_at: datetime | None = None
    time_zone: str = "Europe/Paris"
    created_at: datetime
    contact_count: int = 0
    sent_count: int = 0


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    business_name: str
    first_name: str
    last_name: str
    role: str
    email: str
    phone: str
    city: str
    website: str
    source: str
    status: str
    opted_out: bool
    score: int
    tags: str
    email_subject: str = ""
    email_message: str = ""
    whatsapp_message: str = ""
    sms_message: str = ""


class SequenceStepCreate(BaseModel):
    channel: str
    provider: str
    delay_hours: int = Field(default=0, ge=0, le=8760)
    subject: str = ""
    message: str
    stop_on_reply: bool = True


class SequenceStepOut(SequenceStepCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int


class TemplateCreate(BaseModel):
    name: str
    channel: str
    subject: str = ""
    message: str
    category: str = "general"


class TemplateOut(TemplateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HandoverUpdate(BaseModel):
    paused: bool


class SheetImportRequest(BaseModel):
    spreadsheet: str
    sheet_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str


class ProspectingJobCreate(BaseModel):
    query: str = Field(min_length=2, max_length=240)
    location: str = Field(min_length=2, max_length=240)
    limit: int = Field(default=50, ge=1, le=500)


class ProspectToCampaign(BaseModel):
    campaign_id: int
    prospect_ids: list[int] = []


class ProspectMessageUpdate(BaseModel):
    email_subject: str = Field(max_length=240)
    email_message: str
    whatsapp_message: str
    sms_message: str = Field(max_length=160)


class GenerateMessageRequest(BaseModel):
    channel: str
    sector: str = ""
    audience: str = ""
    objective: str = "book_meeting"
    offer: str
    tone: str = "direct, chaleureux et professionnel"
    calendar_url: str = ""
    video_url: str = ""
    extra_instructions: str = ""


class SendRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=500)
    confirm_live: bool = False


class ScheduleCampaignRequest(BaseModel):
    scheduled_at: datetime
    confirm_live: bool = False


class RuntimeModeUpdate(BaseModel):
    dry_run: bool
    confirm_live: bool = False


class SuppressionCreate(BaseModel):
    value: str = Field(min_length=3)
    reason: str = "opt-out"
