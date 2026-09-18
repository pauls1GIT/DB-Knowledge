from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_COLUMNS = {"ticket_id", "subject", "description", "status"}
OPTIONAL_COLUMNS = {
    "created_date",
    "resolved_date",
    "category",
    "sub_category",
    "priority",
    "resolution",
    "product_service",
    "department",
    "satisfaction_rating",
    "time_to_resolution_hours",
    "text_length",
}

# Common structured identifiers worth preserving exactly for deterministic retrieval.
ERROR_PATTERNS = [
    re.compile(r"\bORA-\d{3,6}\b", re.IGNORECASE),
    re.compile(r"\bHTTP\s*[-:]?\s*[1-5]\d{2}\b", re.IGNORECASE),
    re.compile(r"\bCAM-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2,10}-\d{3,8}\b"),
]


def clean(value: Any) -> str:
    if value is None:
        return ""
    # pandas NaN is the only normal value that is not equal to itself.
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return str(value).strip()


def extract_error_code(*parts: Any) -> str:
    text = "\n".join(clean(part) for part in parts if clean(part))
    for pattern in ERROR_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(0).upper()
            return re.sub(r"^HTTP\s*[-:]?\s*", "HTTP ", value)
    return ""


@dataclass(frozen=True)
class CsvIncident:
    external_key: str
    summary: str
    description: str
    resolution: str
    error_code: str
    status: str
    category: str = ""
    sub_category: str = ""
    priority: str = ""
    product_service: str = ""
    department: str = ""
    created_date: str = ""
    resolved_date: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.status.casefold() in {"resolved", "closed"} and bool(self.resolution)

    @property
    def search_query(self) -> str:
        parts = [self.summary, self.description, self.error_code, self.product_service]
        return " ".join(part for part in parts if part).strip()


def incident_from_row(row: Mapping[str, Any]) -> CsvIncident:
    missing = REQUIRED_COLUMNS.difference(row.keys())
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    subject = clean(row.get("subject"))
    description = clean(row.get("description"))
    resolution = clean(row.get("resolution"))
    return CsvIncident(
        external_key=clean(row.get("ticket_id")),
        summary=subject,
        description=description,
        resolution=resolution,
        error_code=extract_error_code(subject, description, resolution),
        status=clean(row.get("status")),
        category=clean(row.get("category")),
        sub_category=clean(row.get("sub_category")),
        priority=clean(row.get("priority")),
        product_service=clean(row.get("product_service")),
        department=clean(row.get("department")),
        created_date=clean(row.get("created_date")),
        resolved_date=clean(row.get("resolved_date")),
    )


def resolve_csv_path(local_path: Path, bundled_path: Path) -> Path:
    """Prefer the PC dataset when available; hosted apps use the deployment copy."""
    return local_path if local_path.is_file() else bundled_path
