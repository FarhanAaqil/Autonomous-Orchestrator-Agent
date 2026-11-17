"""Account email transport; tokens, addresses and message content are never logged."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

from orchestrator_core.config import get_settings

logger = logging.getLogger(__name__)


def send_account_link(email, purpose, token):
    settings = get_settings()
    if not settings.smtp_host:
        if settings.environment != 'development':
            raise RuntimeError('Account email delivery is not configured')
        logger.info('Development account email suppressed; configure a private SMTP test inbox to receive links')
        return
    # Fragment keeps recovery credentials out of HTTP access logs and referrers.
    link = settings.public_base_url.rstrip('/') + '/#' + urlencode({'action': purpose, 'token': token})
    message = EmailMessage()
    message['From'] = settings.smtp_from
    message['To'] = email
    message['Subject'] = 'Verify your Toji email' if purpose == 'verify' else 'Reset your Toji password'
    message.set_content('Use this one-time link: ' + link + '\nIf you did not request this, ignore this email.')
    context = ssl.create_default_context()
    transport = smtplib.SMTP_SSL if settings.smtp_tls == 'ssl' else smtplib.SMTP
    options = {'context': context} if settings.smtp_tls == 'ssl' else {}
    with transport(settings.smtp_host, settings.smtp_port, timeout=10, **options) as client:
        if settings.smtp_tls == 'starttls':
            client.starttls(context=context)
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or '')
        client.send_message(message)
