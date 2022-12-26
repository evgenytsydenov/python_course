import os

import traitlets.config
from dotenv import load_dotenv

from settings import DATE_FORMAT, DB_URL, LOG_FORMAT_INFO, LOG_PATH

load_dotenv()

try:
    # This is used when Jupyter starts or Nbgrader is called from the console
    config = get_config()  # type: ignore[name-defined]
except NameError:
    # This is used when Nbgrader is called from scripts
    config = traitlets.config.get_config()

# Logging settings
os.makedirs(LOG_PATH, exist_ok=True)
config.Application.log_level = "INFO"
config.Application.log_datefmt = DATE_FORMAT
config.Application.log_format = LOG_FORMAT_INFO
config.NbGrader.logfile = os.path.join(LOG_PATH, "formgrader.log")

# Course settings
config.CourseDirectory.course_id = os.environ["COURSE_NAME"]
config.CourseDirectory.root = os.path.dirname(os.path.abspath(__file__))
config.CourseDirectory.db_url = DB_URL

# Increase timeout to 180 seconds
config.ExecutePreprocessor.timeout = 180

# The text snippet that will replace written solutions
config.ClearSolutions.text_stub = ""

# The code snippet that will replace code solutions
config.ClearSolutions.code_stub = {"python": ""}
