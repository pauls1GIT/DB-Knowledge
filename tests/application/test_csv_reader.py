import pytest
from kedb.infrastructure.csv.jira_csv_reader import JiraCsvReader


def test_reader_accepts_minimum_jira_columns():
    rows=JiraCsvReader().read(b"Issue key,Summary,Description\nABC-1,Failure,broken\n")
    assert rows[0]["Issue key"]=="ABC-1"


def test_reader_rejects_missing_issue_key():
    with pytest.raises(ValueError): JiraCsvReader().read(b"Summary\nFailure\n")
