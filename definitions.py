import os

from sqlalchemy.engine import URL

ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

LOG_FORMAT_DEBUG = (
    "%(asctime)s | %(name)s | %(funcName)s " "| %(levelname)s | %(message)s"
)
LOG_FORMAT_INFO = "%(asctime)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S %Z"
TASK_NAME_PATTERN = r"^#### TODO:\s+(?P<name>.+)$"
PUBLISH_IGNORE = [".ipynb_checkpoints"]
DB_URL = str(
    URL(
        drivername=os.environ["DB_DRIVER"],
        username=os.environ["DB_GRADER_USER"],
        password=os.environ["DB_GRADER_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        database=os.environ["DB_NAME"],
        query={"charset": "utf8mb4"},
    )
)
