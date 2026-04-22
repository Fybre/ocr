from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from ..database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    source = Column(String, nullable=False)  # api_sync | api_async | upload | folder
    status = Column(String, nullable=False, default="pending")  # pending | processing | done | failed
    processing_mode = Column(String, nullable=False, default="auto")  # auto | machine | handwriting | image_description
    engine_used = Column(String, nullable=True)
    detected_content_type = Column(String, nullable=True)  # printed | handwritten | mixed | unknown
    output_format = Column(String, nullable=False, default="plain")  # plain | markdown
    page_count = Column(Integer, nullable=True)
    confidence_score = Column(Float, nullable=True)
    result_text = Column(Text, nullable=True)
    bounding_boxes_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    webhook_url = Column(String, nullable=True)
    webhook_status = Column(String, nullable=True)  # pending | delivered | failed
    webhook_attempts = Column(Integer, nullable=False, default=0)
    languages = Column(String, nullable=False, default="eng")
    llm_provider = Column(String, nullable=False, default="auto")
    file_path = Column(String, nullable=False)
    result_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
