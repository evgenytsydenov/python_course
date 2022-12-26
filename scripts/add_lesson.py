import datetime
import os

from dotenv import load_dotenv
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

from nbgrader_config import config
from utils import app_logger

load_dotenv()
logger = app_logger.get_logger("scripts.add_lesson")


def add_lesson(
    nbgrader_config: Config, lesson_name: str, due_date: datetime.datetime | None = None
) -> None:
    """Add lesson to the grading system.

    Args:
        nbgrader_config: Grader configuration.
        lesson_name: Name of the lesson.
        due_date: Deadline for the lesson.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    lesson_name = lesson_name.strip()
    if not lesson_name:
        raise ValueError("You must specify non-empty lesson name.")
    with nb.gradebook as gb:
        gb.check_course(course_id)
        logger.debug("Database was checked.")
        gb.add_assignment(name=lesson_name, duedate=due_date, course_id=course_id)
        logger.info(f'The lesson "{lesson_name}" was added to the course "{course_id}"')

    path = os.path.join("..", "source", lesson_name)
    if not os.path.exists(path):
        os.makedirs(path)
        logger.info(f'Source folder for the lesson "{lesson_name}" was created.')


if __name__ == "__main__":
    add_lesson(nbgrader_config=config, lesson_name="Loops")
