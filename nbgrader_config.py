import os

import traitlets.config  # type: ignore[import]
from dotenv import load_dotenv

from definitions import DATE_FORMAT, DB_URL, LOG_FORMAT_INFO, ROOT_PATH

load_dotenv()

try:
    # This is used when Jupyter starts or Nbgrader is called from console
    config = get_config()
except NameError:
    # This is used when Nbgrader is called from scripts
    config = traitlets.config.get_config()

# Logging settings
log_path = os.path.join(ROOT_PATH, "logs")
if not os.path.exists(log_path):
    os.makedirs(log_path)
config.Application.log_level = "INFO"
config.Application.log_datefmt = DATE_FORMAT
config.Application.log_format = LOG_FORMAT_INFO
config.NbGrader.logfile = os.path.join(log_path, "formgrader.log")

# Course settings
config.CourseDirectory.course_id = os.environ["COURSE_NAME"]
config.CourseDirectory.root = ROOT_PATH
config.CourseDirectory.db_url = DB_URL

# Increase timeout to 180 seconds
config.ExecutePreprocessor.timeout = 180

# The text snippet that will replace written solutions
config.ClearSolutions.text_stub = ""

# The code snippet that will replace code solutions
config.ClearSolutions.code_stub = {"python": ""}
