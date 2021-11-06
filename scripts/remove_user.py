import os
import shutil

from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

# noinspection PyUnresolvedReferences
import shared
from definitions import ROOT_PATH
from nbgrader_config import config
from utils import app_logger

logger = app_logger.get_logger('scripts.remove_user')


def remove_user(nbgrader_config: Config, user_id: str) -> None:
    """Remove all data about user.

    :param nbgrader_config: grader configuration.
    :param user_id: username.
    """
    nb = NbGraderAPI(config=nbgrader_config)
    with nb.gradebook as gb:
        gb.remove_student(user_id)
        for folder in ['autograded', 'feedback', 'submitted']:
            path = os.path.join(ROOT_PATH, folder, user_id)
            if os.path.exists(path):
                shutil.rmtree(path)
    logger.info(f'User with id "{user_id}" was removed.')


if __name__ == '__main__':
    user = '20'
    remove_user(config, user)
