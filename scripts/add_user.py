import re
import uuid

from email_validator import EmailNotValidError, validate_email
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

from nbgrader_config import config
from utils import app_logger

logger = app_logger.get_logger("scripts.add_user")


def normalize_email(email: str) -> str | None:
    """Normalize email.

    :param email: email to validate.
    :return: Normalized email or None if email is not valid.
    """
    try:
        valid = validate_email(email.strip())
        return valid.email.lower()
    except EmailNotValidError:
        return None


def clean_string(text: str) -> str:
    """Remove all special characters and convert to lower case.

    :param text: text to handle.
    :return: cleaned text.
    """
    pattern = "[^A-Za-z0-9]+"
    return re.sub(pattern, "", text).lower()


def add_user(
    nbgrader_config: Config,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    group: str | None = None,
) -> None:
    """Add new user.

    :param nbgrader_config: grader configuration.
    :param first_name: user's first name.
    :param last_name: user's last name.
    :param email: user's email.
    :param group: user's group.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    with nb.gradebook as gb:
        gb.check_course(course_id)
        emails = {st.email for st in gb.students}

        # Check if such email already exists
        email_ = normalize_email(email)
        if not email_:
            raise ValueError(f'Email "{email}" is incorrect."')
        if email_ in emails:
            raise ValueError(f'User with email "{email_}" ' f"already exists.")

        # Create username
        first_name_ = clean_string(first_name)
        last_name_ = clean_string(last_name)
        parts = [n for n in [last_name_, first_name_] if n]
        username = "_".join([*parts, uuid.uuid1().hex])[:128]

        # Add
        gb.add_student(
            student_id=username,
            first_name=first_name,
            email=email_,
            last_name=last_name,
            lms_user_id=group,
        )
        logger.info(f'User "{username}" was added.')


if __name__ == "__main__":
    add_user(
        first_name="Ted",
        last_name="Mosby",
        email="tedmosby@architect.com",
        nbgrader_config=config,
    )
