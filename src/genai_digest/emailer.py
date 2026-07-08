from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import EmailConfig


def send_email(email_config: EmailConfig, subject: str, html_body: str, text_body: str) -> None:
    if not email_config.is_ready:
        raise ValueError("Email configuration is incomplete.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_config.from_email
    message["To"] = email_config.to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port, timeout=30) as server:
        if email_config.smtp_use_tls:
            server.starttls()
        if email_config.smtp_username and email_config.smtp_password:
            server.login(email_config.smtp_username, email_config.smtp_password)
        server.send_message(message)

