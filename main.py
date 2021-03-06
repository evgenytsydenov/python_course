import json
import os
import traceback
from datetime import datetime
from datetime import timezone
from typing import Dict

from dotenv import load_dotenv

from definitions import DATE_FORMAT
from definitions import ROOT_PATH
from exchanger.engine import GmailExchanger
from exchanger.feedback import FeedbackCreator
from grader.engine import Grader
from nbgrader_config import config
from publisher.engine import GDrivePublisher
from utils.app_logger import get_logger
from utils.data_models import GradeStatus
from utils.smtp_sender import SMTPSender

load_dotenv()
logger = get_logger(__name__)


def sync_release_folder(gdrive_publisher: GDrivePublisher) -> None:
    """Sync local releases with the cloud ones.

    :param gdrive_publisher: publisher instance.
    """
    release_path = os.path.join(ROOT_PATH, 'release')
    if not os.path.exists(release_path):
        os.makedirs(release_path)
    for lesson in os.listdir(release_path):
        gdrive_publisher.sync(os.path.join(release_path, lesson), 'release')
    logger.info('Local release versions of assignments '
                'were synchronized with the cloud ones.')


def sync_html_sources(gdrive_publisher: GDrivePublisher) -> Dict[str, str]:
    """Sync html source files with the cloud ones.

    :param gdrive_publisher: publisher instance.
    :return: filenames and their links.
    """
    pic_path = os.path.join(ROOT_PATH, 'exchanger', 'resources', 'pics')
    links = {}
    for pic in os.listdir(pic_path):
        image_name = os.path.splitext(pic)[0]
        link = gdrive_publisher.sync(os.path.join(pic_path, pic),
                                     'html_sources', 'const_thumbnail')
        links[image_name] = link
    logger.info('Local html sources were synchronized with the cloud ones.')
    return links


if __name__ == '__main__':

    # To fetch submissions and send feedbacks
    exchanger = GmailExchanger(
        creds=json.loads(os.environ['GMAIL_CREDS']),
        fetch_label=os.environ['GMAIL_FETCH_LABEL'],
        send_name=os.environ['GMAIL_SEND_NAME'],
        send_email=os.environ['GMAIL_SEND_EMAIL'],
        path_downloaded=os.path.join(ROOT_PATH, 'downloaded'))

    # To grade submissions
    grader = Grader(config)

    # To publish release version of assignments
    publisher = GDrivePublisher(
        creds=json.loads(os.environ['GDRIVE_CREDS']),
        cloud_root_name=os.environ['GDRIVE_PUBLISH_FOLDER'])

    try:
        # Make init preparations
        exchanger.connect(
            to_create_filter=True,
            fetch_keyword=os.environ['GMAIL_FETCH_KEYWORD'],
            fetch_alias=os.environ['GMAIL_FETCH_ALIAS'])
        publisher.connect()

        # Sync local release folder with the cloud one
        sync_release_folder(publisher)

        # To create feedback messages
        feedback_maker = FeedbackCreator(
            course_name=os.environ['COURSE_NAME'],
            teacher_email=os.environ['TEACHER_EMAIL'],
            picture_links=sync_html_sources(publisher))

        logger.info('Start grading process.')
        while True:

            # New submissions will be saved in downloads directory
            new_submissions = exchanger.fetch_new_submissions()

            # Grade all new submissions
            for submission in new_submissions:

                # Check parameters of the submission and grade it
                grade_result = grader.grade_submission(submission)

                if grade_result.status is not GradeStatus.SKIPPED:
                    # Create feedback
                    feedback = feedback_maker.get_feedback(grade_result)

                    # Send feedback
                    exchanger.send_feedback(feedback)

                # Mark submission as graded
                exchanger.mark_as_completed(submission.exchange_id)
    except (KeyboardInterrupt, SystemExit):
        pass
    except:
        logger.critical('Unhandled exception occurred.', exc_info=True)
        smtp_sender = SMTPSender(login=os.environ['SERVICE_EMAIL_LOGIN'],
                                 password=os.environ['SERVICE_EMAIL_PASSWORD'],
                                 server=os.environ['SERVICE_EMAIL_SERVER'],
                                 server_port=os.environ['SERVICE_EMAIL_PORT'])
        date = datetime.now(timezone.utc).strftime(DATE_FORMAT)
        subject = f'Grader of {os.environ["COURSE_NAME"]} failed at {date}'
        smtp_sender.send(destination=os.environ['TEACHER_EMAIL'],
                         plain_text=f'{traceback.format_exc()}',
                         subject=subject)
    finally:
        grader.stop()
