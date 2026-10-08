from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_FIELDS = {"ticket_id", "subject", "description", "status"}
OPTIONAL_FIELDS = {
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
class Incident:
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


def incident_from_row(row: Mapping[str, Any]) -> Incident:
    missing = REQUIRED_FIELDS.difference(row.keys())
    if missing:
        raise ValueError(f"Incident is missing required fields: {', '.join(sorted(missing))}")

    subject = clean(row.get("subject"))
    description = clean(row.get("description"))
    resolution = clean(row.get("resolution"))
    return Incident(
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


def resolve_json_path(local_path: Path, bundled_path: Path) -> Path:
    """Prefer the PC dataset when available; hosted apps use the deployment copy."""
    return local_path if local_path.is_file() else bundled_path


def incidents_from_json(payload: Any) -> list[Incident]:
    """Read an array of ticket objects; reject malformed input atomically."""
    if not isinstance(payload, list):
        raise ValueError("JSON input must be an array of ticket objects")
    incidents = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"Ticket {index + 1} must be an object")
        for field in REQUIRED_FIELDS | {"resolution"}:
            if field not in row or (row[field] is not None and not isinstance(row[field], str)):
                raise ValueError(f"Ticket {index + 1}: {field} must be a string or null")
        incident = incident_from_row(row)
        if not incident.external_key or not incident.summary or not incident.status:
            raise ValueError(f"Ticket {index + 1} requires nonempty ticket_id, subject and status")
        incidents.append(incident)
    return incidents


def batch_items(incidents):
    items, seen = [], set()
    for incident in incidents:
        if not incident.is_resolved or incident.external_key in seen:
            continue
        if not incident.external_key:
            raise ValueError("Resolved ticket is missing its key")
        seen.add(incident.external_key)
        items.append({key: getattr(incident, key) for key in
                      ("external_key", "summary", "description", "resolution", "error_code")})
    return items
