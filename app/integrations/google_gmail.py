"""Gmail integration — send emails via SMTP.

The bot can:
- Send plain text emails
- Send HTML emails
- Send emails with CC/BCC

Uses SMTP (smtp.gmail.com) with App Password for personal Gmail accounts.
To set up:
1. Enable 2-Step Verification on your Google account
2. Create an App Password at https://myaccount.google.com/apppasswords
3. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger('integrations.gmail')

_GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS', '')
_GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')
_GMAIL_DISPLAY_NAME = os.getenv('GMAIL_DISPLAY_NAME', 'Hub Automacao')


def is_configured():
    """Check if Gmail SMTP is configured."""
    return bool(_GMAIL_ADDRESS and _GMAIL_APP_PASSWORD)


def send_email(to, subject, body, html=False, cc=None, bcc=None, sender=None):
    """Send an email via SMTP. Returns True on success, None on failure.

    to: recipient email (string or list)
    subject: email subject
    body: email body (plain text or HTML)
    html: if True, body is treated as HTML
    cc: CC recipients (string or list)
    bcc: BCC recipients (string or list)
    """
    if not is_configured():
        log.warning('[GMAIL] SMTP not configured (set GMAIL_ADDRESS + GMAIL_APP_PASSWORD)')
        return None

    from_email = sender or _GMAIL_ADDRESS
    from_header = f'{_GMAIL_DISPLAY_NAME} <{from_email}>'

    if isinstance(to, list):
        to_str = ', '.join(to)
        to_list = list(to)
    else:
        to_str = to
        to_list = [to]

    if html:
        message = MIMEMultipart('alternative')
        message.attach(MIMEText(body, 'html'))
    else:
        message = MIMEText(body)

    message['to'] = to_str
    message['from'] = from_header
    message['subject'] = subject

    all_recipients = list(to_list)

    if cc:
        cc_list = cc if isinstance(cc, list) else [cc]
        message['cc'] = ', '.join(cc_list)
        all_recipients.extend(cc_list)
    if bcc:
        bcc_list = bcc if isinstance(bcc, list) else [bcc]
        all_recipients.extend(bcc_list)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(_GMAIL_ADDRESS, _GMAIL_APP_PASSWORD)
            server.sendmail(from_email, all_recipients, message.as_string())
        log.info(f'[GMAIL] Sent to {to_str}: {subject}')
        return True
    except smtplib.SMTPAuthenticationError as e:
        log.error(f'[GMAIL] Authentication failed. Check GMAIL_APP_PASSWORD: {e}')
        return None
    except Exception as e:
        log.error(f'[GMAIL] Send failed: {e}')
        return None


def send_lead_followup(to_email, lead_name, tenant_name, message_body):
    """Send a follow-up email to a lead."""
    subject = f'{tenant_name} - Seguimento'
    greeting = f'Ola {lead_name},' if lead_name else 'Ola,'

    body = f"""{greeting}

{message_body}

Atenciosamente,
{tenant_name}
"""
    return send_email(to_email, subject, body)


def send_notification(to_email, subject, details):
    """Send an internal notification email (e.g., new lead alert)."""
    body = f"""Notificacao automatica do Hub Automacao Pro:

{details}

---
Este email foi enviado automaticamente pelo sistema.
"""
    return send_email(to_email, subject, body)
