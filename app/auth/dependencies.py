import hashlib
from datetime import datetime

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.api_key import ApiKey


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(
    x_api_key: str = Header(..., description="API key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    key_hash = _hash_key(x_api_key)
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == True,
    ).first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    api_key.last_used_at = datetime.utcnow()
    db.commit()
    return api_key
