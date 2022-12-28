import base64
import contextlib
import os
import pickle
import re
import shutil
import socket
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from functools import partial, wraps
from typing import Any, Callable

import requests
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from jpgrader.app_logger import get_logger
from jpgrader.data_models import Feedback, Submission
from settings import DATE_FORMAT

logger = get_logger(__name__)


# TODO: Provide type annotation
def slow_api_calls(
    func: Callable[..., Any] | None = None, *, min_latency: float = 1
) -> Any:
    """Decorator to prevent exceeding of frequency rate limits of API calls.

    Args:
        func: Function to decorate.
        min_latency: Minimal time of the latency between API calls in seconds.

    Returns:
        Decorated function.
    """
    if func is None:
        return partial(slow_api_calls, min_latency=min_latency)

    @wraps(func)
    def _wrapper(*args, **kwargs):  # type: ignore[no-untyped-def] # noqa[ANN202]
        time_diff = time.time() - _wrapper.last_call  # type: ignore[attr-defined]
        if time_diff < min_latency:
            time.sleep(min_latency - time_diff)
        _wrapper.last_call = time.time()  # type: ignore[attr-defined]
        return func(*args, **kwargs)  # type: ignore[misc]

    _wrapper.last_call = time.time()  # type: ignore[attr-defined]
    return _wrapper


# TODO: Provide type annotation
def repeat_request(
    func: Callable[..., Any] | None = None,
    *,
    recreate_resource: bool = True,
    time_delay: list[int] | None = None,
) -> Any:
    """Decorator for repeating gmail API calls.

    Intended to overcome connection issues. The requests will be repeated with a time
    delay until the request is successful.

    Args:
        time_delay: List of time delays in minutes to wait before trying the request
            again. If this parameter is not specified, the following values will be
            used: [1, 2, 5, 10].
        func: Function to decorate.
        recreate_resource: Whether the gmail resource should be rebuilt.

    Returns:
        Decorated function.
    """
    if func is None:
        return partial(
            repeat_request, recreate_resource=recreate_resource, time_delay=time_delay
        )

    delays = time_delay or [1, 2, 5, 10]

    @wraps(func)
    def _wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def] # noqa[ANN202]
        error = Exception("The request was not completed.")
        for timeout in delays:
            try:
                return func(self, *args, **kwargs)  # type: ignore[misc]
            except (
                ConnectionError,
                TransportError,
                HttpError,
                requests.exceptions.ConnectionError,
                socket.timeout,
                socket.gaierror,
            ) as err:
                logger.debug(f"Failed with {type(err).__name__}.", exc_info=True)
                error = err
                sleep_time = timeout * 60
                logger.debug(f"Sleep for {sleep_time} seconds.")
                time.sleep(sleep_time)
                if recreate_resource:
                    logger.debug("Recreate Gmail resource.")
                    self._gmail = self._build_resource()
                logger.debug("Request again.")
        logger.warning("The number of attempts is over.")
        raise error

    return _wrapper


class GmailExchanger:
    """Use Gmail API for exchange."""

    def __init__(
        self,
        creds: dict[str, Any],
        fetch_label: str,
        send_name: str,
        send_email: str,
        path_downloaded: str,
    ) -> None:
        """Create Gmail exchanger.

        Args:
            creds: OAuth2 credentials that should be downloaded from the Gmail API
                console.
            fetch_label: Email label to monitor. Each message with this label will
                be considered as a submission.
            send_name: Name of the sender for outgoing messages.
            send_email: Email of the sender to show in outgoing messages.
            path_downloaded: Where to save attachments.
        """
        self._creds = creds
        self._fetch_label = fetch_label
        self._send_email = send_email
        self._send_name = send_name
        self._path_downloaded = path_downloaded
        self._path_pickle = os.path.join("credentials", "gmail.pickle")
        self._scopes = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.settings.basic",
        ]
        self._gmail_resource: Resource | None = None
        self._label_id: str | None = None

    @property
    def _gmail(self) -> Resource:
        if self._gmail_resource is None:
            raise RuntimeError('The method "connect" must be called first.')
        return self._gmail_resource

    def connect(
        self,
        to_create_filter: bool = False,
        fetch_keyword: str | None = None,
        fetch_alias: str | None = None,
    ) -> None:
        """Perform start up preparations.

        User authorization is performed, and the necessary label is
        created or found among the existing labels.

        Args:
            to_create_filter: If the email filter should be created.
            fetch_keyword: All messages containing this keyword in the subject will
                be marked with the fetcher label (must be specified when
                `to_create_filter` is True).
            fetch_alias: Email to which the submissions are sent (must be specified
                when `to_create_filter` is True).
        """
        # Build gmail api resource
        self._gmail_resource = self._build_resource()

        # Create label if not exists
        self._label_id = self._create_label(self._fetch_label)

        # Create filter for submissions
        if to_create_filter:
            self._create_filter(
                self._label_id, fetch_keyword=fetch_keyword, fetch_alias=fetch_alias
            )
        logger.info("Gmail exchanger started successfully.")

    def fetch_new_submissions(self) -> list[Submission]:
        """Fetch new submissions from gmail.

        Each unread message with <GMAIL_LABEL> is handled as a new submission.
        Attachments of such message will be unpacked and saved to the specified
        path for downloads.

        Returns:
            New submissions.
        """
        # Get new submissions
        message_ids = self._get_new_messages()

        # Parse each submission
        submissions = []
        for mes_id in message_ids:
            logger.debug(f'Start parsing submission with the id "{mes_id}".')
            msg = self._load_message(mes_id)
            new_submission = Submission(
                email=self._extract_email(msg),
                lesson_name=self._extract_lesson_name(msg),
                timestamp=self._extract_timestamp(msg),
                file_path=self._extract_attachments(msg),
                submission_id=mes_id,
            )
            submissions.append(new_submission)
            logger.info(
                f'The data of the submission with the id "{mes_id}" '
                f"was downloaded and parsed."
            )
        return submissions

    @slow_api_calls(min_latency=5)  # type: ignore[misc]
    @repeat_request
    def _get_new_messages(self) -> list[str]:
        """Fetch new messages with submissions.

        Returns:
            List with IDs of unread messages.
        """
        query = "is:unread"
        result = (
            self._gmail.users()
            .messages()
            .list(userId="me", q=query, labelIds=[self._label_id])
            .execute()
        )
        return [msg["id"] for msg in result.get("messages", {})]

    @repeat_request
    def send_feedback(self, feedback: Feedback) -> None:
        """Send HTML feedback.

        Args:
            feedback: Feedback that contains an email address, subject and html content.
        """
        # Create message
        message = MIMEMultipart()
        message["to"] = formataddr((feedback.student_name, feedback.email))
        message["from"] = formataddr((self._send_name, self._send_email))
        message["subject"] = feedback.subject
        message.attach(MIMEText(feedback.html_body, "html"))
        raw_message = base64.urlsafe_b64encode(message.as_string().encode("utf-8"))
        msg_decoded = {"raw": raw_message.decode("utf-8")}

        # Send message
        self._gmail.users().messages().send(userId="me", body=msg_decoded).execute()
        logger.debug(f'The message "{feedback.subject} was sent to "{feedback.email}".')
        logger.info(
            f'The feedback for the submission "{feedback.submission_id}" was sent.'
        )

    @repeat_request
    def mark_as_completed(self, message_id: str) -> None:
        """Mark that the submission was graded and the feedback was sent.

        After submission handling, its message is marked as READ
        so that it will not be handled with the next fetching.

        Args:
            message_id: ID of the message.
        """
        mods = {"addLabelIds": [], "removeLabelIds": ["UNREAD"]}
        self._gmail.users().messages().modify(
            body=mods, userId="me", id=message_id
        ).execute()
        logger.debug(f'Message with the id "{message_id}" was marked as read.')
        logger.info(f'Submission with the id "{message_id}" was marked as graded.')

    # TODO: Can be used without browser?
    @repeat_request(recreate_resource=False)  # type: ignore[misc]
    def _build_resource(self) -> Any:
        """Build gmail api resource.

        The first start requires to approve the access of this app to the gmail data.

        Returns:
            Resource for interactions.
        """
        creds = None
        if os.path.exists(self._path_pickle):
            with open(self._path_pickle, "rb") as token:
                creds = pickle.load(token)
                logger.debug("The credentials were loaded.")
        elif not os.path.isdir(os.path.dirname(self._path_pickle)):
            os.makedirs(os.path.dirname(self._path_pickle))
            logger.debug("The directory for credentials was created.")

        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                logger.debug("Credentials were refreshed.")
            else:
                flow = InstalledAppFlow.from_client_config(self._creds, self._scopes)
                creds = flow.run_local_server(open_browser=False)
                logger.debug("Credentials were created.")

            # Save the credentials for the next run
            with open(self._path_pickle, "wb") as token:
                pickle.dump(creds, token)
                logger.debug("Credentials were saved.")
        _gmail = build("gmail", "v1", credentials=creds)
        logger.debug("New Gmail resource was created.")
        return _gmail

    @repeat_request
    def _download_attachment(self, msg_id: str, att_id: str) -> str:
        """Download message attachment.

        Sometimes, the attachment is not included in the message,
        so it is necessary to download it separately.

        Args:
            msg_id: Message ID.
            att_id: Attachment ID.

        Returns:
            Attachment data.
        """
        att = (
            self._gmail.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=att_id)
            .execute()
        )
        logger.debug(
            f'Attachment with the id "{att_id}" of the message '
            f'with the id "{msg_id}" was downloaded.'
        )
        return str(att["data"])

    @repeat_request
    def _load_message(self, message_id: str) -> dict[str, Any]:
        """Download message content.

        Args:
            message_id: ID of the message to download.

        Returns:
            Message content.
        """
        content: dict[str, Any] = (
            self._gmail.users().messages().get(userId="me", id=message_id).execute()
        )
        logger.debug(
            f'Content of the message with the id "{message_id}" was downloaded.'
        )
        return content

    @repeat_request
    def _create_label(self, label_name: str) -> str:
        """Create new label or get information about the existing one.

        Args:
            label_name: Name of the label to create.

        Returns:
            ID of the label.
        """
        # Get all existing labels
        all_labels = self._gmail.users().labels().list(userId="me").execute()
        logger.debug("All user labels were loaded.")
        label_info: dict[str, Any] = next(
            (label for label in all_labels["labels"] if label["name"] == label_name),
            {},
        )
        if label_info:
            logger.debug(f'The gmail label "{label_info}" already exists.')
        else:
            body = {
                "name": label_name,
                "messageListVisibility": "show",
                "labelListVisibility": "labelShow",
            }
            label_info = (
                self._gmail.users().labels().create(userId="me", body=body).execute()
            )
            logger.debug(f'The new label "{label_info}" was created.')
        return str(label_info["id"])

    @repeat_request
    def _create_filter(
        self, label_id: str, fetch_keyword: str, fetch_alias: str
    ) -> None:
        """Create filter to catch submissions.

        Args:
            label_id: ID of the label to mark submissions.
            fetch_keyword: All messages containing this keyword in the subject
                will be marked with the label which ID is `label_id`.
            fetch_alias: Email where submissions are sent.
        """
        # Get all existing filters
        filters = self._gmail.users().settings().filters().list(userId="me").execute()
        logger.debug("All filters of the user was requested.")

        # Find if already exist
        criteria = {"to": fetch_alias, "subject": fetch_keyword}
        action = {"addLabelIds": [label_id], "removeLabelIds": ["INBOX", "SPAM"]}
        filter_info: dict[str, Any] = next(
            (
                gmail_filter
                for gmail_filter in filters["filter"]
                if (gmail_filter["criteria"] == criteria)
                and (gmail_filter["action"] == action)
            ),
            {},
        )
        if filter_info:
            logger.debug(f'The filter "{filter_info}" already exists.')
        else:
            body = {"criteria": criteria, "action": action}
            self._gmail.users().settings().filters().create(
                userId="me", body=body
            ).execute()
            logger.debug(f'The filter "{filter_info}" has been created.')

    def _extract_email(self, msg: dict[str, Any]) -> str:
        """Extract sender's email from the message data.

        Args:
            msg: Message data.

        Returns:
            Email.
        """
        headers = msg["payload"]["headers"]
        sender = str(next(x for x in headers if x["name"] == "From")["value"])
        match = re.search(".*<(?P<email>.*)>.*", sender)
        if match:
            sender = match["email"]
        sender = sender.strip()
        logger.debug(
            f'Sender email "{sender}" was extracted '
            f'from the message with the id "{msg["id"]}".'
        )
        return sender

    def _extract_lesson_name(self, msg: dict[str, Any]) -> str:
        """Extract the lesson name from the message data.

        It is considered that each message with the submission has a subject of
        the structure "<gmail_keyword> / <lesson_name>".

        Args:
            msg: Message data.

        Returns:
            Lesson name.
        """
        headers = msg["payload"]["headers"]
        subject = next(x for x in headers if x["name"] == "Subject")["value"]
        match = re.search("^(?P<label>.*)/(?P<lesson>.*)$", subject)
        les_name = match["lesson"].strip() if match else ""
        logger.debug(
            f'Lesson name "{les_name}" was extracted '
            f'from the message with the id "{msg["id"]}".'
        )
        return les_name

    def _extract_timestamp(self, msg: dict[str, Any]) -> datetime:
        """Extract timestamp from message data.

        Extracts the timestamp set by Gmail, not user's one.

        Args:
            msg: Message data.

        Returns:
            Timestamp in UTC.
        """
        utc_time = datetime.utcfromtimestamp(int(msg["internalDate"]) / 1000).replace(
            tzinfo=timezone.utc
        )
        logger.debug(
            f'Timestamp "{utc_time.strftime(DATE_FORMAT)}" '
            f'was extracted from the message with the id "{msg["id"]}".'
        )
        return utc_time

    def _extract_attachments(self, msg: dict[str, Any]) -> str:
        """Extract files from message data.

        Saves all attachments of the message to the specified folder.
        If the attachment is a ZIP or TAR archive, it will be unpacked.

        Args:
            msg: Message data.

        Returns:
            Path to the folder where the attachments were saved.
        """
        # Create folder to save
        path = os.path.join(self._path_downloaded, msg["id"])
        if os.path.exists(path):
            logger.debug(
                f'The folder "{path}" already exists. Its content will be overwritten.'
            )
            shutil.rmtree(path)
        os.makedirs(path)

        # Save attachments
        for part in msg["payload"].get("parts", {}):
            if not part["filename"]:
                continue
            if "data" in part["body"]:
                data = part["body"]["data"]
            else:
                att_id = part["body"]["attachmentId"]
                data = self._download_attachment(msg["id"], att_id)
            file_data = base64.urlsafe_b64decode(data.encode("UTF-8"))
            file_path = os.path.join(path, part["filename"])
            with open(file_path, "wb") as f:
                f.write(file_data)
                logger.debug(
                    f'Attachment "{part["filename"]}" of the '
                    f'message with the id "{msg["id"]}" was saved '
                    f'to "{file_path}".'
                )

        # Extract files from archives
        # If several archives, they will be unpacked and the same
        # content will be overwritten
        for file in os.listdir(path):
            self._unpack_archived_files(os.path.join(path, file))
        return path

    def _unpack_archived_files(self, path_file: str) -> None:
        """Unpack archived file to the same directory.

        If the file specified is not an archive, it will be skipped.

        Args:
            path_file: Path to the archived file.
        """
        folder_path = os.path.dirname(path_file)
        with contextlib.suppress(shutil.ReadError):
            shutil.unpack_archive(path_file, folder_path)
            logger.debug(f'File "{path_file}" was unpacked.')
            os.remove(path_file)
            logger.debug(f'File "{path_file}" was removed.')
