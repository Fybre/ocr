#!/usr/bin/env python3
"""
Create an API key and print it to stdout.

Usage:
    python scripts/create_api_key.py --name "My App"
"""
import argparse
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import create_tables, SessionLocal
from app.models.api_key import ApiKey
from datetime import datetime

KEY_PREFIX = "ocr_"


def main():
    parser = argparse.ArgumentParser(description="Create an OCR API key")
    parser.add_argument("--name", required=True, help="Display name for the key")
    args = parser.parse_args()

    settings.ensure_dirs()
    create_tables()

    raw_key = KEY_PREFIX + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12]

    db = SessionLocal()
    try:
        api_key = ApiKey(
            name=args.name,
            key_hash=key_hash,
            prefix=prefix,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
    finally:
        db.close()

    print(f"\nAPI key created successfully!")
    print(f"  Name:   {args.name}")
    print(f"  ID:     {api_key.id}")
    print(f"  Prefix: {prefix}…")
    print(f"\n  Key (save this — it will not be shown again):")
    print(f"  {raw_key}\n")


if __name__ == "__main__":
    main()
