from kedb.application.csv_incidents import extract_error_code, incident_from_row


def test_ticket_csv_mapping():
    incident = incident_from_row({
        "ticket_id": "TKT-1",
        "subject": "Oracle timeout ORA-12170",
        "description": "Database connection fails.",
        "resolution": "Listener was restored.",
        "status": "Resolved",
        "category": "Database",
        "sub_category": "Connectivity",
        "priority": "High",
        "product_service": "Oracle",
    })
    assert incident.external_key == "TKT-1"
    assert incident.summary == "Oracle timeout ORA-12170"
    assert incident.error_code == "ORA-12170"
    assert incident.is_resolved is True


def test_error_code_empty_when_not_present():
    assert extract_error_code("ordinary ticket text") == ""


def test_csv_path_uses_deployed_copy_when_pc_file_unavailable(tmp_path):
    from kedb.application.csv_incidents import resolve_csv_path
    local = tmp_path / "pc" / "tickets_clean.csv"
    bundled = tmp_path / "data" / "tickets_clean.csv"
    bundled.parent.mkdir()
    bundled.write_text("ticket_id,subject,description,status\n")
    assert resolve_csv_path(local, bundled) == bundled
    local.parent.mkdir()
    local.write_text("local dataset")
    assert resolve_csv_path(local, bundled) == local
