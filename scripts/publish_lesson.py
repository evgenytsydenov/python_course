import json
import os
import re
from typing import Iterable

from dotenv import load_dotenv
from jpgrader import app_logger
from jpgrader.publisher.engine import GDrivePublisher
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

from nbgrader_config import config

logger = app_logger.get_logger("scripts.publish_lesson")
load_dotenv()


def generate_assignments(nbgrader_config: Config, lesson_names: Iterable[str]) -> None:
    """Generate student version of assignments.

    Args:
        nbgrader_config: Nbgrader config.
        lesson_names: Names of the lessons to generate.
    """
    # Check database
    nb = NbGraderAPI(config=nbgrader_config)
    course_id = nbgrader_config.CourseDirectory.course_id
    with nb.gradebook as gb:
        gb.check_course(course_id)
        logger.debug("Database was checked.")

    for lesson in lesson_names:
        result = nb.generate_assignment(lesson)
        logs = re.sub(r"\[\w+\] ", "", result["log"]).replace("\n", ". ")
        if result["success"]:
            logger.debug(f"Grader output: {logs}")
            logger.info(f'Lesson "{lesson}" was generated.')
        else:
            logger.error(f"Grader output: {logs}")
            raise RuntimeError(f'Generating of the lesson "{lesson}" failed.')


if __name__ == "__main__":
    # Lessons to release
    lessons = ["Loops"]

    # Generate student version
    if lessons is None:
        lessons = os.listdir(os.path.join("..", "source"))
    elif isinstance(lessons, str):
        lesson_names = [lessons]
    generate_assignments(config, lessons)

    # Publish
    publisher = GDrivePublisher(
        creds=json.loads(os.environ["GDRIVE_CREDS"]),
        cloud_root_name=os.environ["GDRIVE_PUBLISH_FOLDER"],
    )
    publisher.connect()
    for lesson in lessons:
        path = os.path.join("..", "release", lesson)
        publisher.sync(path, "release")
        logger.info(
            f'Local release version of the assignment "{lesson}" '
            f"was synchronized with the cloud one."
        )
