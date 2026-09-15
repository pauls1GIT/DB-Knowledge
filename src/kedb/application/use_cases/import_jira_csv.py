from __future__ import annotations

from kedb.application.services.jira_csv_mapper import JiraCsvMapper


class ImportJiraCsv:
    def __init__(self, repo, reader, mapper: JiraCsvMapper | None = None):
        self.repo = repo
        self.reader = reader
        self.mapper = mapper or JiraCsvMapper()

    def execute(self, filename: str, content: bytes, include_unresolved: bool = True) -> dict:
        rows = self.reader.read(content)
        batch = self.repo.create_import_batch(filename=filename, total_rows=len(rows))
        imported = skipped = failed = 0

        for row_number, row in enumerate(rows, start=2):  # header is row 1
            try:
                issue = self.mapper.map(row)
                eligible = bool(issue.resolution.strip() or issue.resolved_at)
                if not include_unresolved and not eligible:
                    self.repo.create_import_item(batch.id, None, row_number, "SKIPPED", "Unresolved issue")
                    skipped += 1
                    continue
                self.repo.save_issue(issue)
                self.repo.create_import_item(batch.id, issue.id, row_number, "PENDING", None)
                imported += 1
            except Exception as exc:
                self.repo.create_import_item(batch.id, None, row_number, "FAILED", str(exc))
                failed += 1

        self.repo.finish_import_batch(batch.id, valid_rows=imported, invalid_rows=failed, skipped_rows=skipped)
        return self.repo.get_import_batch_summary(batch.id)
