import os
import shutil

from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

from definitions import ROOT_PATH
from nbgrader_config import config
from utils import app_logger

logger = app_logger.get_logger("scripts.remove_user")


def remove_user(nbgrader_config: Config, user_id: str) -> None:
    """Remove all data about user.

    Args:
        nbgrader_config: Grader configuration.
        user_id: User ID.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    with nb.gradebook as gb:
        gb.remove_student(user_id)
        logger.debug(
            f'Data of the user with the id "{user_id}" was removed from the database.'
        )
        for folder in ["autograded", "feedback", "submitted"]:
            path = os.path.join(ROOT_PATH, folder, user_id)
            if os.path.exists(path):
                shutil.rmtree(path)
                logger.debug(
                    f'Folder "{path}" of the user with the id "{user_id}" was removed.'
                )
    logger.info(f'User with the id "{user_id}" was removed.')


if __name__ == "__main__":
    user_id = "20"
    remove_user(config, user_id)
