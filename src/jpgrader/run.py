import json
import os
import traceback
from datetime import datetime, timezone
from importlib.resources import files

from dotenv import load_dotenv

from jpgrader.app_logger import get_logger
from jpgrader.data_models import GradeStatus
from jpgrader.exchanger.engine import GmailExchanger
from jpgrader.exchanger.feedback import FeedbackCreator
from jpgrader.grader.engine import Grader
from jpgrader.publisher.engine import GDrivePublisher
from jpgrader.smtp_sender import SMTPSender
from nbgrader_config import config
from settings import DATE_FORMAT

load_dotenv()
logger = get_logger(__name__)


def sync_release_folder(gdrive_publisher: GDrivePublisher) -> None:
    """Sync local releases with the cloud ones.

    Args:
        gdrive_publisher: Publisher instance.
    """
    release_path = "release"
    os.makedirs(release_path, exist_ok=True)
    for lesson in os.listdir(release_path):
        gdrive_publisher.sync(os.path.join(release_path, lesson), "release")
        logger.debug(
            f'Local release version of the lesson "{lesson}" '
            f"was synchronized with the cloud one."
        )
    logger.info(
        "Local release versions of the lessons were synchronized with the cloud ones."
    )


def sync_html_sources(gdrive_publisher: GDrivePublisher) -> dict[str, str]:
    """Sync pictures for HTML emails with the cloud ones.

    Args:
        gdrive_publisher: Publisher instance.

    Returns:
        Filenames and their links.
    """
    pics_path = files("jpgrader.resources.email_pics")
    email_pics = [
        "0_20.png",
        "21_40.png",
        "41_60.png",
        "61_80.png",
        "81_99.png",
        "100.png",
        "check.png",
        "course_icon.png",
        "grader_failed.png",
        "unknown_content.png",
        "unknown_files.png",
        "unknown_lesson.png",
        "unknown_user.png",
        "xmark.png",
    ]
    links = {}
    for pic in email_pics:
        pic_name = os.path.splitext(pic)[0]
        pic_path = str(pics_path.joinpath(pic))
        link = gdrive_publisher.sync(pic_path, "html_sources", "const_thumbnail")
        links[pic_name] = link
        logger.debug(
            f'Local HTML source of the pic "{pic}" was '
            f"synchronized with the cloud ones."
        )
    logger.info("Local HTML sources were synchronized with the cloud ones.")
    return links


def main() -> None:
    """Start the grading system."""
    # To fetch submissions and send feedbacks
    exchanger = GmailExchanger(
        creds=json.loads(os.environ["GMAIL_CREDS"]),
        fetch_label=os.environ["GMAIL_FETCH_LABEL"],
        send_name=os.environ["GMAIL_SEND_NAME"],
        send_email=os.environ["GMAIL_SEND_EMAIL"],
        path_downloaded=os.path.join("downloaded"),
    )

    # To grade submissions
    grader = Grader(config)

    # To publish release version of assignments
    publisher = GDrivePublisher(
        creds=json.loads(os.environ["GDRIVE_CREDS"]),
        cloud_root_name=os.environ["GDRIVE_PUBLISH_FOLDER"],
    )

    try:
        # Make init preparations
        exchanger.connect(
            to_create_filter=True,
            fetch_keyword=os.environ["GMAIL_FETCH_KEYWORD"],
            fetch_alias=os.environ["GMAIL_FETCH_ALIAS"],
        )
        publisher.connect()

        # Sync local release folder with the cloud one
        sync_release_folder(publisher)

        # To create feedback messages
        feedback_maker = FeedbackCreator(
            course_name=os.environ["COURSE_NAME"],
            teacher_email=os.environ["TEACHER_EMAIL"],
            picture_links=sync_html_sources(publisher),
        )

        logger.info("Start the grading process.")
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
                exchanger.mark_as_completed(submission.submission_id)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:  # noqa BLE001
        logger.critical("Unhandled exception occurred.", exc_info=True)
        send_error_report(traceback_str=traceback.format_exc())
    finally:
        grader.stop()


def send_error_report(traceback_str: str) -> None:
    """Send message about.

    Args:
        traceback_str: Exception info.
    """
    smtp_sender = SMTPSender(
        login=os.environ["SERVICE_EMAIL_LOGIN"],
        password=os.environ["SERVICE_EMAIL_PASSWORD"],
        server=os.environ["SERVICE_EMAIL_SERVER"],
        server_port=os.environ["SERVICE_EMAIL_PORT"],
    )
    date = datetime.now(timezone.utc).strftime(DATE_FORMAT)
    subject = (
        f'The grader of the course "{os.environ["COURSE_NAME"]}" failed at {date}.'
    )
    smtp_sender.send(
        destination=os.environ["TEACHER_EMAIL"],
        plain_text=traceback_str,
        subject=subject,
    )


if __name__ == "__main__":
    main()
