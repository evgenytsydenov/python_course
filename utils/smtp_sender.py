import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from utils.app_logger import get_logger

logger = get_logger(__name__)


class SMTPSender:
    """Sender of emails via SMTP."""

    def __init__(self, login: str, password: str, server: str,
                 server_port: str) -> None:
        """Create email sender.

        :param login: mailbox login.
        :param password: mailbox password.
        :param server: mail server address.
        :param server_port: port of mail server.
        """
        self._password = password
        self._login = login
        self._server = server
        self._server_port = int(server_port)

    def send(self, destination: str, subject: str,
             plain_text: Optional[str] = None,
             html_content: Optional[str] = None) -> None:
        """Send message.

        :param plain_text: text message.
        :param destination: destination address.
        :param subject: letter subject.
        :param html_content: html string.
        """
        # Create message
        message = MIMEMultipart()
        message['From'] = self._login
        message['To'] = destination
        message['Subject'] = subject
        if plain_text:
            message.attach(MIMEText(plain_text))
        if html_content:
            message.attach(MIMEText(html_content, 'html'))
        text = message.as_string()

        # Send
        server = smtplib.SMTP(self._server, self._server_port)
        tls_context = ssl.create_default_context()
        try:
            server.ehlo()
            server.starttls(context=tls_context)
            server.ehlo()
            logger.debug(f'Connected to SMTP server: '
                         f'{self._server}:{self._server_port}.')
            server.login(self._login, self._password)
            logger.debug(f'Authentication with login "{self._login}" was '
                         f'successful.')
            server.sendmail(self._login, destination, text)
            logger.info(f'Message "{subject}" was sent to "{destination}".')
        finally:
            server.quit()
