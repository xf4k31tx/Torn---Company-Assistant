from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

from . import secure_storage

# This legacy path is read only for migration; new company data is DPAPI-encrypted
# under the user's LocalAppData folder.
PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
COMPANIES_PATH = PROJECT_ROOT / "companies.json"
_COMPANIES_KEY = "companies"


def load_companies() -> List[Dict]:
    """Load DPAPI-protected company configs; read legacy JSON only if necessary."""
    companies = secure_storage.get(_COMPANIES_KEY)
    if isinstance(companies, list):
        return companies
    if not COMPANIES_PATH.exists():
        return []
    try:
        data = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_companies(companies: List[Dict]) -> None:
    """Persist company data, including API keys, encrypted for this Windows user."""
    secure_storage.set(_COMPANIES_KEY, companies)
