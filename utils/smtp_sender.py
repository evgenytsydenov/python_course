import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from utils.app_logger import get_logger

logger = get_logger(__name__)


class SMTPSender:
    """Sender of emails via SMTP."""

    def __init__(
        self, login: str, password: str, server: str, server_port: str
    ) -> None:
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

    def send(
        self,
        destination: str,
        subject: str,
        plain_text: str | None = None,
        html_content: str | None = None,
        files: list[str] | None = None,
    ) -> None:
        """Send message.

        :param files: path to files to attach.
        :param plain_text: text message.
        :param destination: destination address.
        :param subject: letter subject.
        :param html_content: html string.
        """
        # Create message
        message = MIMEMultipart()
        message["From"] = self._login
        message["To"] = destination
        message["Subject"] = subject
        if plain_text:
            message.attach(MIMEText(plain_text))
        if html_content:
            message.attach(MIMEText(html_content, "html"))
        if files:
            for file in files:
                with open(file, "rb") as file_obj:
                    file_name = os.path.basename(file)
                    file_attachment = MIMEBase("application", "octet-stream")
                    file_attachment.set_payload(file_obj.read())
                    encoders.encode_base64(file_attachment)
                    file_attachment.add_header(
                        "Content-Disposition", f'attachment; filename="{file_name}"'
                    )
                    message.attach(file_attachment)
        text = message.as_string()

        # Send
        server = smtplib.SMTP(self._server, self._server_port)
        tls_context = ssl.create_default_context()
        try:
            server.ehlo()
            server.starttls(context=tls_context)
            server.ehlo()
            logger.debug(
                f"Connected to SMTP server: " f"{self._server}:{self._server_port}."
            )
            server.login(self._login, self._password)
            logger.debug(
                f'Authentication with login "{self._login}" was ' f"successful."
            )
            server.sendmail(self._login, destination, text)
            logger.info(f'Message "{subject}" was sent to "{destination}".')
        finally:
            server.quit()
