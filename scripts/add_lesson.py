import datetime
import os
from typing import Optional

from dotenv import load_dotenv
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

# noinspection PyUnresolvedReferences
import shared
from definitions import ROOT_PATH
from nbgrader_config import config
from utils import app_logger

load_dotenv()
logger = app_logger.get_logger('scripts.add_lesson')


def add_lesson(nbgrader_config: Config, lesson_name: str,
               due_date: Optional[datetime.datetime] = None) -> None:
    """Add lesson to the grading system.

    :param nbgrader_config: grader configuration.
    :param lesson_name: name of the lesson.
    :param due_date: deadline for the lesson.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    lesson_name = lesson_name.strip()
    assert lesson_name, 'You must specify non-empty lesson name.'
    with nb.gradebook as gb:
        gb.check_course(course_id)
        gb.add_assignment(name=lesson_name, duedate=due_date,
                          course_id=course_id)
        logger.info(f'Lesson "{lesson_name}" was added '
                    f'to course "{course_id}"')

    path = os.path.join(ROOT_PATH, 'source', lesson_name)
    if not os.path.exists(path):
        os.makedirs(path)
        logger.info(f'Source folder for the lesson '
                    f'"{lesson_name}" was created.')


if __name__ == '__main__':
    add_lesson(nbgrader_config=config, lesson_name='Loops')
