import os

ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

LOG_FORMAT_DEBUG = '%(asctime)s | %(name)s | %(funcName)s ' \
                   '| %(levelname)s | %(message)s'
LOG_FORMAT_INFO = '%(asctime)s | %(levelname)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S %Z'
TASK_NAME_PATTERN = r'^#### TODO:\s+(?P<name>.+)$'
