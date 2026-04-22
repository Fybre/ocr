from datetime import datetime
from typing import Literal
from pydantic import BaseModel, HttpUrl


ProcessingMode = Literal["auto", "machine", "handwriting", "image_description"]
OutputFormat = Literal["plain", "markdown"]
LlmProvider = Literal["auto", "openai", "azure", "local"]
JobStatus = Literal["pending", "processing", "done", "failed"]
JobSource = Literal["api_sync", "api_async", "upload", "folder"]


class JobCreate(BaseModel):
    mode: ProcessingMode = "auto"
    output_format: OutputFormat = "plain"
    async_mode: bool = False
    webhook_url: str | None = None
    llm_provider: LlmProvider = "auto"
    languages: str = "eng"


class JobReprocess(BaseModel):
    mode: ProcessingMode | None = None
    output_format: OutputFormat | None = None
    llm_provider: LlmProvider | None = None
    languages: str | None = None


class JobResponse(BaseModel):
    id: str
    filename: str
    source: str
    status: str
    processing_mode: str
    engine_used: str | None = None
    detected_content_type: str | None = None
    output_format: str
    page_count: int | None = None
    confidence_score: float | None = None
    webhook_url: str | None = None
    webhook_status: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobResultResponse(JobResponse):
    result_text: str | None = None
    error_message: str | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
