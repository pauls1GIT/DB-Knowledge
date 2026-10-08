from kedb.config import Settings
from kedb.infrastructure import notifications


def test_diagnostic_identifies_timeout(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("private detail")
    monkeypatch.setattr(notifications.smtplib, "SMTP", fail)
    result = notifications.diagnose_smtp(Settings(_env_file=None, smtp_host="smtp.gmail.com", smtp_from="test@example.com"))
    assert result["stage"] == "connect_and_greeting"
    assert result["error_type"] == "TimeoutError"
    assert "private detail" not in str(result)


def test_diagnostic_logs_in_without_sending(monkeypatch):
    calls = []
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def ehlo(self): return 250, b"ok"
        def starttls(self, **kwargs): calls.append("tls")
        def login(self, *args): calls.append("login")
        def close(self): calls.append("close")
    monkeypatch.setattr(notifications.smtplib, "SMTP", SMTP)
    result = notifications.diagnose_smtp(Settings(_env_file=None, smtp_host="smtp.gmail.com", smtp_from="test@example.com", smtp_username="test"))
    assert result["status"] == "ok" and result["email_sent"] is False
    assert calls == ["tls", "login", "close"]
