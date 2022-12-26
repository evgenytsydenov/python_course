import os

from sqlalchemy.engine import URL

# Logs formats
LOG_FORMAT_DEBUG = "%(asctime)s | %(name)s | %(funcName)s | %(levelname)s | %(message)s"
LOG_FORMAT_INFO = "%(asctime)s | %(levelname)s | %(message)s"
LOG_PATH = "logs"

# Date format to use across the project
DATE_FORMAT = "%Y-%m-%d %H:%M:%S %Z"

# Cells with this text will be recognized as tasks
TASK_NAME_PATTERN = r"^#### TODO:\s+(?P<name>.+)$"

# These files will not published to the cloud folder
PUBLISH_IGNORE = [".ipynb_checkpoints"]

# Connection string to the database
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
