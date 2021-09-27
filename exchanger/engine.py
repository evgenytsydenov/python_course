from __future__ import print_function

import base64
import functools
import os
import pickle
import re
import requests
import shutil
import socket
import sys
import time
from datetime import datetime
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from definitions import DATE_FORMAT
from definitions import ROOT_PATH
from utils.app_logger import get_logger
from utils.data_models import Feedback
from utils.data_models import Submission

logger = get_logger(__name__)


def slow_api_calls(func: Optional[Callable] = None, *,
                   min_latency: float = 1) -> Callable:
    """Decorator to prevent exceeding of frequency rate limits of API calls.

    :param func: function to decorate.
    :param min_latency: minimal time of latency between API calls in seconds.
    :return: decorated function.
    """
    if func is None:
        return functools.partial(slow_api_calls, min_latency=min_latency)

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        time_diff = time.time() - _wrapper.last_call
        if time_diff < min_latency:
            time.sleep(min_latency - time_diff)
        _wrapper.last_call = time.time()
        return func(*args, **kwargs)

    _wrapper.last_call = time.time()
    return _wrapper


def repeat_request(func: Optional[Callable] = None, *,
                   recreate_resource: bool = True) -> Callable:
    """Decorator for repeating gmail API calls.

    Intended to overcome connection issues. This will repeat calls with time
    delay in 1, 5, 10, 15, and 20 minutes.

    :param func: function to decorate.
    :param recreate_resource: if gmail service should be rebuilt.
    :return: decorated function.
    """
    if func is None:
        return functools.partial(repeat_request,
                                 recreate_resource=recreate_resource)

    @functools.wraps(func)
    def _wrapper(self, *args, **kwargs):
        for timeout in [1, 5, 10, 15, 20]:
            try:
                return func(self, *args, **kwargs)
            except (ConnectionError, TransportError, HttpError,
                    requests.ConnectionError, socket.timeout) as err:
                error = err
                exc_type, _, _ = sys.exc_info()
                sleep_time = timeout * 60
                logger.debug(f'Failed with {exc_type.__name__}.',
                             exc_info=True)
                logger.debug(f'Sleep for {sleep_time} seconds.')
                time.sleep(sleep_time)
                if recreate_resource:
                    logger.debug('Recreate Gmail resource.')
                    self._gmail = self._build_resource()
                logger.debug('Request again.')
        logger.warning('The number of attempts is over.')
        raise error

    return _wrapper


class GmailExchanger:
    """Use Gmail API for exchange."""

    def __init__(self, creds: Dict[str, Any], fetch_label: str,
                 send_name: str, send_email: str,
                 path_downloaded: str) -> None:
        """Create GmailExchanger.

        :param creds: OAuth2 credentials that should be downloaded from
        Gmail API console.
        :param fetch_label: email label to monitor. Each message with this
        label will be considered as submission.
        :param send_name: sender name for outgoing messages.
        :param send_email: email of sender to show in outgoing messages.
        :param path_downloaded: where to save attachments.
        """
        self._creds = creds
        self._fetch_label = fetch_label
        self._send_email = send_email
        self._send_name = send_name
        self._path_downloaded = path_downloaded
        self._path_pickle = os.path.join(
            ROOT_PATH, 'credentials', 'gmail.pickle')
        self._scopes = ['https://www.googleapis.com/auth/gmail.modify',
                        'https://www.googleapis.com/auth/gmail.settings.basic']
        self._gmail = None
        self._label_id = None

    @repeat_request(recreate_resource=False)
    def _build_resource(self) -> Any:
        """Build gmail api resource.

        The first start requires to approve the access of this app to the
        gmail data.

        :return: resource for interaction.
        """
        creds = None
        if os.path.exists(self._path_pickle):
            with open(self._path_pickle, 'rb') as token:
                creds = pickle.load(token)
        elif not os.path.isdir(os.path.dirname(self._path_pickle)):
            os.makedirs(os.path.dirname(self._path_pickle))

        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_config(
                    self._creds, self._scopes)
                creds = flow.run_local_server(open_browser=False)

            # Save the credentials for the next run
            with open(self._path_pickle, 'wb') as token:
                pickle.dump(creds, token)
        _gmail = build('gmail', 'v1', credentials=creds)
        logger.debug('New Gmail resource was created.')
        return _gmail

    def connect(self, to_create_filter: bool = False,
                fetch_keyword: Optional[str] = None,
                fetch_alias: Optional[str] = None) -> None:
        """Start up preparations.

        Here, user authorization is performed, and the necessary label is
        created or found among the existing labels.

        :param to_create_filter: if a gmail filter should be created.
        :param fetch_alias: email to which the submissions are sent
        (must be  specified when `to_create_filter` is True).
        :param fetch_keyword: all messages containing this keyword in the
        subject will be marked with the fetcher label (must be specified when
        `to_create_filter` is True).
        """

        # Build gmail api resource
        self._gmail = self._build_resource()

        # Create label if not exists
        self._label_id = self._get_label_id(self._fetch_label)

        # Create filter for submissions
        if to_create_filter:
            self._create_filter(self._label_id, fetch_keyword=fetch_keyword,
                                fetch_alias=fetch_alias)
        logger.info('Gmail exchanger started successfully.')

    def fetch_new_submissions(self) -> List[Submission]:
        """Fetch new submissions from gmail.

        Each unread message with <GMAIL_LABEL> is handled as a new submission.
        Attachments of such message will be unpacked and saved
        to the specified path for downloads.

        :return: new submissions.
        """
        # Get new submissions
        message_ids = self._get_new_messages()

        # Parse each submission
        submissions = []
        for mes_id in message_ids:
            logger.info(f'Start parsing submission with id "{mes_id}".')
            msg = self._load_message(mes_id)
            new_submission = Submission(
                email=self._extract_email(msg),
                lesson_name=self._extract_lesson_name(msg),
                timestamp=self._extract_timestamp(msg),
                filepath=self._extract_attachments(msg),
                exchange_id=mes_id)
            submissions.append(new_submission)
            logger.info(f'Submission data from message with id "{mes_id}" '
                        f'was parsed and saved.')
        return submissions

    @slow_api_calls(min_latency=5)
    @repeat_request
    def _get_new_messages(self) -> List[str]:
        """Fetch new messages with submissions.

        :return: list of new message ids.
        """
        query = 'is:unread'
        result = self._gmail.users().messages() \
            .list(userId='me', q=query, labelIds=[self._label_id]).execute()
        return [msg['id'] for msg in result.get('messages', {})]

    @repeat_request
    def mark_as_completed(self, message_id: str) -> None:
        """Mark that the submission was graded and feedback was sent.

        After submission handling, its message is marked as READ so that
        it will not be handled with the next fetching.

        :param message_id: id of message.
        """
        mods = {'addLabelIds': [], 'removeLabelIds': ['UNREAD']}
        self._gmail.users().messages().modify(
            body=mods, userId='me', id=message_id).execute()
        logger.info(f'Message with id "{message_id}" was marked as read.')

    def _extract_email(self, msg: Dict[str, Any]) -> str:
        """Extract sender email from message data.

        :param msg: message data.
        :return: email.
        """
        headers = msg['payload']['headers']
        sender = next(x for x in headers if x['name'] == 'From')['value']
        match = re.search('.*<(?P<email>.*)>.*', sender)
        if match:
            sender = match.group('email')
        logger.debug(f'Sender email "{sender}" was extracted '
                     f'from the message with id "{msg["id"]}".')
        return sender

    def _extract_lesson_name(self, msg: Dict[str, Any]) -> str:
        """Extract lesson name from message data.

        It is considered that each message with submission has a subject of
        the structure "<gmail_keyword> / <lesson_name>".

        :param msg: message data.
        :return: lesson name.
        """
        headers = msg['payload']['headers']
        subject = next(x for x in headers if x['name'] == 'Subject')['value']
        match = re.search('^(?P<label>.*)/(?P<lesson>.*)$', subject)
        les_name = ''
        if match:
            les_name = match.group('lesson')
        logger.debug(f'Lesson name "{les_name}" extracted '
                     f'from the message with id "{msg["id"]}".')
        return les_name

    def _extract_timestamp(self, msg: Dict[str, Any]) -> datetime:
        """Extract timestamp from message data.

        This extracts the timestamp set by Gmail, not user's one.

        :param msg: message data.
        :return: timestamp in UTC.
        """
        utc_time = datetime.utcfromtimestamp(
            int(msg['internalDate']) / 1000).replace(tzinfo=timezone.utc)
        logger.debug(f'Timestamp "{utc_time.strftime(DATE_FORMAT)}" '
                     f'was extracted from the message with id "{msg["id"]}".')
        return utc_time

    @repeat_request
    def _extract_attachments(self, msg: Dict[str, Any]) -> str:
        """Extract files from message data.

        This saves all attachments of the message to the specified folder for
        downloads. If the attachment is a ZIP or TAR archive, it will be
        unpacked.

        :param msg: message data.
        :return: path to folder where data was saved.
        """
        # Create folder for submission content
        path = os.path.join(self._path_downloaded, msg['id'])
        if os.path.exists(path):
            logger.warning(f'The folder "{path}" already exists. '
                           f'Its content will be overwritten.')
            shutil.rmtree(path)
        os.makedirs(path)

        # Download attachments
        for part in msg['payload'].get('parts', {}):
            if not part['filename']:
                continue
            if 'data' in part['body']:
                data = part['body']['data']
            else:
                att_id = part['body']['attachmentId']
                att = self._gmail.users().messages().attachments() \
                    .get(userId='me', messageId=msg['id'], id=att_id) \
                    .execute()
                data = att['data']
            file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
            file_path = os.path.join(path, part['filename'])
            with open(file_path, 'wb') as f:
                f.write(file_data)
                logger.debug(f'Attachment "{part["filename"]}" of the '
                             f'message with id "{msg["id"]}" was saved '
                             f'to "{file_path}".')

        # Extract files from archives
        for file in os.listdir(path):
            path_file = os.path.join(path, file)
            try:
                shutil.unpack_archive(path_file, path)
                logger.debug(f'File "{path_file}" was unpacked.')
                os.remove(path_file)
            except shutil.ReadError:
                pass
        return path

    @repeat_request
    def _load_message(self, message_id: str) -> Dict[str, Any]:
        """Download message content.

        :param message_id: id of the message.
        :return: message content.
        """
        content = self._gmail.users().messages() \
            .get(userId='me', id=message_id).execute()
        logger.debug(f'Content of the message with '
                     f'id "{message_id}" was downloaded.')
        return content

    @repeat_request
    def send_feedback(self, feedback: Feedback) -> None:
        """Send html feedback.

        :param feedback: feedback that contains email address, subject and
        html content.
        """
        # Create message
        message = MIMEMultipart()
        message['to'] = formataddr((feedback.student_name, feedback.email))
        message['from'] = formataddr((self._send_name, self._send_email))
        message['subject'] = feedback.subject
        message.attach(MIMEText(feedback.html_body, 'html'))
        raw_message = base64.urlsafe_b64encode(
            message.as_string().encode('utf-8'))
        message = {'raw': raw_message.decode('utf-8')}

        # Send message
        self._gmail.users().messages() \
            .send(userId='me', body=message).execute()
        logger.info(f'Message "{feedback.subject}" was sent '
                    f'to "{feedback.email}".')

    @repeat_request
    def _get_label_id(self, label_name: str) -> str:
        """Create new label or get information about existing one.

        :param: label_name: name of label to create.
        :return: label id.
        """
        all_labels = self._gmail.users().labels().list(userId='me').execute()
        label_info = {}
        for label in all_labels['labels']:
            if label['name'] == label_name:
                label_info = label
                break
        if label_info:
            logger.debug(f'Gmail label "{label_info}" already exists.')
        else:
            body = {'name': label_name, 'messageListVisibility': 'show',
                    'labelListVisibility': 'labelShow'}
            label_info = self._gmail.users().labels() \
                .create(userId='me', body=body).execute()
            logger.debug(f'New label "{label_info}" was created.')
        return label_info['id']

    @repeat_request
    def _create_filter(self, label_id: str, fetch_keyword: str,
                       fetch_alias: str) -> None:
        """Create filter for submissions.

        :param label_id: id of label to mark submissions.
        :param fetch_alias: email where submissions are sent.
        :param fetch_keyword: all messages containing this keyword in the
        subject will be marked with the `label_id`.
        """
        # List all filters
        filters = self._gmail.users().settings().filters() \
            .list(userId='me').execute()

        # Find if already exist
        criteria = {'to': fetch_alias, 'subject': fetch_keyword}
        action = {'addLabelIds': [label_id],
                  'removeLabelIds': ['INBOX', 'SPAM']}
        filter_info = {}
        for gmail_filter in filters['filter']:
            if (gmail_filter['criteria'] == criteria) \
                    and (gmail_filter['action'] == action):
                filter_info = gmail_filter
                break

        if filter_info:
            logger.debug(f'Filter {filter_info} already exists.')
        else:
            body = {'criteria': criteria, 'action': action}
            self._gmail.users().settings().filters() \
                .create(userId='me', body=body).execute()
            logger.debug(f'Filter {filter_info} has been created.')
