import json
import os
import re
from typing import Iterable, Union

from dotenv import load_dotenv
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

# noinspection PyUnresolvedReferences
import shared
from definitions import ROOT_PATH
from nbgrader_config import config
from publisher.engine import GDrivePublisher
from utils import app_logger

logger = app_logger.get_logger('scripts.release_lesson')
load_dotenv()


def generate_assignments(
        nbgrader_config: Config,
        lesson_names: Union[Iterable[str], str, None] = None) -> None:
    """Generate student version of assignments.

    :param nbgrader_config: nbgrader config.
    :param lesson_names: names of lessons to generate or None for all lessons.
    """
    if lesson_names is None:
        lesson_names = os.listdir(os.path.join(ROOT_PATH, 'source'))
    elif isinstance(lesson_names, str):
        lesson_names = [lesson_names]

    # Check database
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    with nb.gradebook as gb:
        gb.check_course(course_id)

    for lesson in lesson_names:
        result = nb.generate_assignment(lesson)
        logs = re.sub(r'\[\w+\] ', '', result['log']).replace('\n', '. ')
        if result['success']:
            logger.debug(f'Grader output: {logs}')
            logger.info(f'Lesson "{lesson}" was generated.')
        else:
            logger.error(f'Grader output: {logs}')
            raise SystemError(f"Generating of '{lesson}' failed.")


if __name__ == '__main__':
    # Lessons to release
    lessons = ['Loops']

    # Generate student version
    generate_assignments(config, lessons)

    # Publisher
    publisher = GDrivePublisher(
        creds=json.loads(os.environ['GDRIVE_CREDS']),
        cloud_root_name=os.environ['GDRIVE_PUBLISH_FOLDER'])
    publisher.connect()

    # Publish
    for lesson in lessons:
        path = os.path.join(ROOT_PATH, 'release', lesson)
        publisher.sync(path, 'release')
        logger.info(f'Local release version of the assignment "{lesson}" '
                    f'was synchronized with the cloud one.')
