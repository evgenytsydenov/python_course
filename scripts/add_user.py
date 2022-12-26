import uuid

from email_validator import EmailNotValidError, validate_email
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

from nbgrader_config import config
from utils import app_logger

logger = app_logger.get_logger("scripts.add_user")


def normalize_email(email: str) -> str | None:
    """Normalize email.

    Args:
        email: Email to normalize.

    Returns:
        Normalized email or None if email is not valid.
    """
    try:
        valid = validate_email(email.strip())
        return str(valid.email).lower()
    except EmailNotValidError:
        return None


def add_user(
    nbgrader_config: Config,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    group: str | None = None,
) -> None:
    """Add a new user.

    Args:
        nbgrader_config: Grader configuration.
        email: User's email.
        first_name: User's first name.
        last_name: User's last name.
        group: User's group.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    user_id = uuid.uuid1().hex
    logger.debug(f'Start adding a new user with the id "{user_id}".')
    with nb.gradebook as gb:
        gb.check_course(course_id)
        logger.debug("Database was checked.")
        emails = {st.email for st in gb.students}

        # Check if such email already exists
        email_ = normalize_email(email)
        if not email_:
            raise ValueError(f'Email "{email}" is incorrect.')
        if email_ in emails:
            raise ValueError(f'User with the email "{email_}" already exists.')

        # Add
        gb.add_student(
            student_id=user_id,
            first_name=first_name,
            email=email_,
            last_name=last_name,
            lms_user_id=group,
        )
        logger.info(f'The user "{user_id}" with email "{email_}" was added.')


if __name__ == "__main__":
    add_user(
        first_name="Ted",
        last_name="Mosby",
        email="tedmosby@architect.com",
        nbgrader_config=config,
    )
