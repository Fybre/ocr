import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models.api_key import ApiKey
from ..schemas.api_key import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])

KEY_PREFIX = "ocr_"
KEY_BYTES = 32  # 32 random bytes → 64 hex chars


def _generate_key() -> str:
    return KEY_PREFIX + secrets.token_hex(KEY_BYTES)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _check_admin(x_admin_token: str | None = Header(None)) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
def create_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    _: None = Depends(_check_admin),
) -> ApiKeyCreatedResponse:
    raw_key = _generate_key()
    api_key = ApiKey(
        name=body.name,
        key_hash=_hash_key(raw_key),
        prefix=raw_key[:12],
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    response = ApiKeyCreatedResponse.model_validate(api_key)
    response.key = raw_key
    return response


@router.get("", response_model=list[ApiKeyResponse])
def list_keys(
    db: Session = Depends(get_db),
    _: None = Depends(_check_admin),
) -> list[ApiKeyResponse]:
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=204)
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_check_admin),
) -> None:
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    db.commit()
