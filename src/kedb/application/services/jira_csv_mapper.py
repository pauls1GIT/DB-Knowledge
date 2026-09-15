from __future__ import annotations

from kedb.domain.entities import JiraIssue
from kedb.infrastructure.csv.jira_csv_reader import parse_jira_datetime


class JiraCsvMapper:
    """Map Jira-export column names to the normalized JiraIssue domain entity."""

    def map(self, row: dict) -> JiraIssue:
        return JiraIssue(
            external_key=(row.get("Issue key") or "").strip(),
            external_id=(row.get("Issue id") or None),
            summary=(row.get("Summary") or "").strip(),
            description=(row.get("Description") or "").strip(),
            resolution=(row.get("Resolution") or "").strip(),
            error_code=self._extract_error_code(row),
            status=(row.get("Status") or None),
            priority=(row.get("Priority") or None),
            issue_type=(row.get("Issue Type") or None),
            environment=(row.get("Environment") or None),
            parent_external_key=(row.get("Parent key") or None),
            resolved_at=parse_jira_datetime(row.get("Resolved")),
            source_created_at=parse_jira_datetime(row.get("Created")),
            source_updated_at=parse_jira_datetime(row.get("Updated")),
            raw_payload=row,
        )

    @staticmethod
    def _extract_error_code(row: dict) -> str | None:
        # Jira exports do not have a universal error-code column. Preserve a future
        # explicit Error code field if present; deterministic extraction can be added later.
        return (row.get("Error code") or row.get("Error Code") or "").strip() or None
