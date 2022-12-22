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

        Args:
            login: Mailbox login.
            password: Mailbox password.
            server: Server address.
            server_port: Port of the mail server.
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

        Args:
            destination: Destination address.
            subject: Letter subject.
            plain_text: Text message.
            html_content: HTML string.
            files: Path to files to attach.
        """
        message = self._create_message(
            destination, subject, plain_text, html_content, files
        )
        server = smtplib.SMTP(self._server, self._server_port)
        tls_context = ssl.create_default_context()
        try:
            server.ehlo()
            server.starttls(context=tls_context)
            server.ehlo()
            logger.debug("Connected to the SMTP server.")
            server.login(self._login, self._password)
            logger.debug("Authentication was successful.")
            server.sendmail(self._login, destination, message)
            logger.info(f'Message "{subject}" was sent to "{destination}".')
        finally:
            server.quit()
            logger.debug("Logged out from the SMTP server.")

    def _create_message(
        self,
        destination: str,
        subject: str,
        plain_text: str | None = None,
        html_content: str | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Create message.

        Args:
            destination: Destination address.
            subject: Letter subject.
            plain_text: Text message.
            html_content: Html string.
            files: Path to files to attach.

        Returns:
            Message as an encoded string.
        """
        message = MIMEMultipart()
        message["From"] = self._login
        message["To"] = destination
        message["Subject"] = subject
        logger.debug(f'New message "{subject}" to "{destination}" was created.')
        if plain_text:
            message.attach(MIMEText(plain_text))
            logger.debug("Plain text was attached to the message.")
        if html_content:
            message.attach(MIMEText(html_content, "html"))
            logger.debug("HTML content was attached to the message.")
        files = [] if files is None else files
        for file in files:
            message.attach(self._load_attachment(file))
            logger.debug(f'File "{file}" was attached to the message.')
        return message.as_string()

    def _load_attachment(self, file_path: str) -> MIMEBase:
        """Load file content.

        Args:
            file_path:
                Path to the file.

        Returns:
            File content as attachment.
        """
        with open(file_path, "rb") as file_obj:
            file_name = os.path.basename(file_path)
            file_attachment = MIMEBase("application", "octet-stream")
            file_attachment.set_payload(file_obj.read())
            encoders.encode_base64(file_attachment)
            file_attachment.add_header(
                "Content-Disposition", f'attachment; filename="{file_name}"'
            )
            return file_attachment
