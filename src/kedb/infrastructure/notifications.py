"""Email similar published knowledge to the reporter of a new Jira issue."""
import smtplib
from email.message import EmailMessage


def send_candidates(settings, issue, recipient, candidates):
    if not settings.smtp_host or not settings.smtp_from:
        raise ValueError("Configure SMTP_HOST and SMTP_FROM")
    if not recipient or "@" not in recipient or "\n" in recipient or "\r" in recipient:
        raise ValueError("Jira reporter email is missing or invalid")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = f"Similar known errors for {issue.external_key}"
    lines = [f"{issue.external_key}: {issue.summary}", "", "Similar candidates:"]
    for candidate in candidates:
        lines.extend([f"{candidate.rank}. {candidate.title} (similarity {candidate.final_score:.2f})",
                      f"Known error: {candidate.known_error_id}",
                      candidate.resolution or "", ""])
    if not candidates:
        lines.append("No similar published known errors were found.")
    message.set_content("\n".join(lines))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def diagnose_smtp(settings):
    """Check configured SMTP transport and credentials without sending a message."""
    import ssl
    import time
    started = time.monotonic()
    stage = "configuration"
    smtp = None
    try:
        if not settings.smtp_host or not settings.smtp_from:
            raise ValueError("Missing SMTP configuration")
        stage = "connect_and_greeting"
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5)
        stage = "ehlo"
        code, _ = smtp.ehlo()
        if code != 250:
            raise smtplib.SMTPHeloError(code, b"EHLO rejected")
        if settings.smtp_starttls:
            stage = "starttls"
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if settings.smtp_username:
            stage = "authentication"
            smtp.login(settings.smtp_username, settings.smtp_password)
        return {"status": "ok", "stage": "complete", "email_sent": False,
                "elapsed_seconds": round(time.monotonic() - started, 2)}
    except (OSError, ValueError) as exc:
        # Do not return raw server responses, credentials or recipient information.
        return {"status": "failed", "stage": stage, "error_type": type(exc).__name__,
                "smtp_code": getattr(exc, "smtp_code", None), "errno": getattr(exc, "errno", None),
                "elapsed_seconds": round(time.monotonic() - started, 2), "email_sent": False}
    finally:
        if smtp is not None:
            smtp.close()


def candidate_email(issue_key, summary, candidates):
    """Plain text and escaped HTML suitable for Jira's email action."""
    from html import escape
    lines = [f"{issue_key}: {summary}", "", "Similar known errors:", ""]
    rows = []
    for c in candidates:
        rows.append({"rank": c.rank, "title": c.title, "score": c.final_score,
                     "known_error_id": str(c.known_error_id), "resolution": c.resolution or ""})
        lines.extend([f"{c.rank}. {c.title} (similarity {c.final_score:.2f})",
                      f"Known error: {c.known_error_id}", c.resolution or "No resolution text available.", ""])
    if not rows:
        lines.append("No similar published known errors were found.")
    body = "\n".join(lines)
    return {"status": "candidates_ready", "candidate_count": len(rows), "candidates": rows,
            "email_subject": f"Similar known errors for {issue_key}",
            "email_body": body, "email_body_html": "<div>" + escape(body).replace("\n", "<br>") + "</div>"}
