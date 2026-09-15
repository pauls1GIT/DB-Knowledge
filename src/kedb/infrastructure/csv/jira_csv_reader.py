from __future__ import annotations

import csv
import io
from datetime import datetime

DATE_FORMATS = ("%d/%b/%y %I:%M %p", "%d/%b/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_jira_datetime(value: str | None) -> datetime | None:
    value = _clean(value)
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


class JiraCsvReader:
    """Parse a Jira CSV export without leaking CSV concerns into application logic."""

    REQUIRED_COLUMNS = {"Issue key", "Summary"}

    def read(self, content: bytes) -> list[dict]:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        missing = self.REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required Jira CSV columns: {', '.join(sorted(missing))}")
        return [dict(row) for row in reader]
