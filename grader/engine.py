import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from json import JSONDecodeError

from dateutil import parser
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config

import alembic.command
import alembic.config
from grader.database import DatabaseHandler
from settings import DATE_FORMAT, TASK_NAME_PATTERN
from utils.app_logger import get_logger
from utils.data_models import GradeResult, GradeStatus, Submission, Task

logger = get_logger(__name__)


class Grader:
    """Grader class."""

    def __init__(self, grader_config: Config) -> None:
        """Create grader.

        Args:
            grader_config: Grader configuration.
        """
        self._config = grader_config
        self._db = DatabaseHandler(self._config.CourseDirectory.db_url)
        self._nb_grader = NbGraderAPI(config=self._config)
        self._check_schema()
        logger.info("Grader started successfully.")

    def grade_submission(self, submission: Submission) -> GradeResult:
        """Grade submission.

        This will check submission parameters (user id, lesson name, etc.). If they are
        correct, the submission will be graded.

        Args:
            submission: Submission.

        Returns:
            Grading result
        """
        logger.info(f"Start grading the submission: {submission.submission_id}.")
        grade_result = GradeResult(
            submission_id=submission.submission_id,
            status=GradeStatus.SUCCESS,
            timestamp=submission.timestamp,
            email=submission.email,
        )
        log_msg_drop = (
            f'Data of the submission "{submission.submission_id}" was '
            f"dropped from the downloaded folder."
        )

        # Get user information
        user_info = self._db.get_user_info(submission.email)
        if not user_info:
            logger.info(
                f"The information about the user with "
                f'the email "{submission.email}" was not found.'
            )
            grade_result.status = GradeStatus.ERROR_USERNAME_IS_ABSENT
            shutil.rmtree(submission.file_path)
            logger.debug(log_msg_drop)
            return grade_result
        user_ = user_info["id"]
        grade_result.email = user_info["email"]
        grade_result.student_id = user_info["id"]
        grade_result.first_name = user_info["first_name"]
        grade_result.last_name = user_info["last_name"]
        logger.debug(f'The submission is from the user "{user_}".')

        # Get lesson information
        lesson_info = self._db.get_lesson_info(submission.lesson_name)
        if not lesson_info:
            logger.info(
                f"The information about the lesson with the name "
                f'"{submission.lesson_name}" was not found.'
            )
            grade_result.status = GradeStatus.ERROR_LESSON_IS_ABSENT
            shutil.rmtree(submission.file_path)
            logger.debug(log_msg_drop)
            return grade_result
        lesson_ = lesson_info["name"]
        grade_result.lesson_name = lesson_info["name"]
        logger.debug(f'The submission is for the lesson "{lesson_}".')

        # Check if the file for this lesson exists
        notebook_ = self._get_notebook_name(lesson_)
        notebook_path = os.path.join(submission.file_path, f"{notebook_}.ipynb")
        if (notebook_ is None) or (not os.path.exists(notebook_path)):
            logger.info("The notebook for grading was not found among submitted files.")
            grade_result.status = GradeStatus.ERROR_NO_CORRECT_FILES
            shutil.rmtree(submission.file_path)
            logger.debug(log_msg_drop)
            return grade_result
        logger.debug(f'The notebook for grading was found at "{notebook_path}".')

        # Check if the submission is newer than the existing one
        submitted_path = os.path.join("submitted", user_, lesson_)
        if not self._is_submission_newer(submitted_path, submission.timestamp):
            logger.info("The submission is not newer than the existing one. Skip it.")
            grade_result.status = GradeStatus.SKIPPED
            shutil.rmtree(submission.file_path)
            logger.debug(log_msg_drop)
            return grade_result
        logger.debug("This submission is newer than the previous.")

        # Check the notebook structure
        if not self._is_notebook_valid(submission.file_path, lesson_, notebook_):
            logger.info(f'The structure of the notebook "{notebook_}" is corrupted.')
            grade_result.status = GradeStatus.ERROR_NOTEBOOK_CORRUPTED
            shutil.rmtree(submission.file_path)
            logger.debug(log_msg_drop)
            return grade_result
        logger.debug(f'This notebook "{notebook_path}" is valid.')

        # Test the submission
        self._move_checked_files(
            submission.file_path, submitted_path, submission.timestamp
        )
        if not self._autograde(lesson_, user_):
            grade_result.status = GradeStatus.ERROR_GRADER_FAILED
            return grade_result
        grades = self._get_submission_grades(lesson_, notebook_, user_)
        grade_result.task_grades = grades

        # Generate standard feedback
        feedback = self._create_nbgrader_feedback(lesson_, notebook_, user_)

        # Save submission info to database
        with open(os.path.join(submitted_path, f"{notebook_}.ipynb"), "rb") as f:
            notebook = f.read()
        self._db.log_submission(
            user_, lesson_, grades, submission.timestamp, feedback, notebook
        )
        logger.info(
            f'The submission with the id "{submission.submission_id}" was graded.'
        )
        return grade_result

    def _move_checked_files(
        self, downloaded_path: str, submitted_path: str, timestamp: datetime
    ) -> None:
        """Move files from downloaded folder to submitted folder.

        Args:
            downloaded_path: Path to files in the downloaded folder.
            submitted_path: Path to files in the submitted folder.
            timestamp: Submission timestamp.
        """
        # Copy all files
        if os.path.exists(submitted_path):
            shutil.rmtree(submitted_path)
            logger.debug(f'The submitted directory "{submitted_path}" was cleared.')
        shutil.copytree(downloaded_path, submitted_path)

        # Add timestamp information
        timestamp_path = os.path.join(submitted_path, "timestamp.txt")
        with open(timestamp_path, "w") as file:
            timestamp_str = timestamp.strftime(DATE_FORMAT)
            file.write(timestamp.strftime(DATE_FORMAT))
            logger.debug(
                f'The timestamp "{timestamp_str}" was written to "{timestamp_path}".'
            )
        logger.debug(f'Submission files were moved to "{submitted_path}".')

        # Remove files from downloaded folder
        shutil.rmtree(downloaded_path)
        logger.debug(f'Downloaded files were removed from "{downloaded_path}".')

    def _autograde(self, lesson_name: str, user_id: str) -> bool:
        """Run autograding process.

        Args:
            lesson_name: Name of the lesson.
            user_id: User ID.

        Returns:
            Whether the autograding was successful.
        """
        logger.debug(
            f'Start autograding of the user "{user_id}" for the lesson "{lesson_name}.'
        )
        status = self._nb_grader.autograde(lesson_name, user_id, create=False)
        logs = re.sub(r"\[\w+\] ", "", status["log"]).replace("\n", ". ")
        logger.debug(f"Grader output: {logs}")
        if not status["success"]:
            logger.error(f'Traceback: {status.get("error")}')
            with self._nb_grader.gradebook as gb:
                gb.remove_submission(lesson_name, user_id)
                logger.debug(
                    f'The submission of the user "{user_id}" for the lesson '
                    f'"{lesson_name}" was removed from the database.'
                )
            path_ = os.path.join("submitted", user_id, lesson_name)
            if os.path.exists(path_):
                shutil.rmtree(path_)
                logger.debug(f'The submitted directory "{path_}" was cleared.')
            return False
        logger.debug(
            f'Submission of the user "{user_id}" for '
            f'the lesson "{lesson_name}" was autograded.'
        )
        return True

    def _create_nbgrader_feedback(
        self, lesson_name: str, notebook_name: str, user_id: str
    ) -> bytes:
        """Generate standard nbgrader feedback.

        Args:
            lesson_name: Name of the lesson.
            notebook_name: Name of the notebook.
            user_id: User ID.

        Returns:
            Feedback content.
        """
        logger.debug(
            f"Start generating nbgrader feedback of the user "
            f"{user_id} with the lesson {lesson_name}."
        )
        status = self._nb_grader.generate_feedback(lesson_name, user_id)
        logs = re.sub(r"\[\w+\] ", "", status["log"]).replace("\n", ". ")
        if not status["success"]:
            logger.error(f"Grader output: {logs}")
            raise RuntimeError(
                f"Generating nbgrader feedback of the user "
                f"{user_id} with the lesson {lesson_name} failed."
            )
        logger.debug(f"Grader output: {logs}")
        fb_path = os.path.join(
            "feedback", user_id, lesson_name, f"{notebook_name}.html"
        )
        logger.debug(
            f'Nbgrader feedback of the user "{user_id}" with the lesson '
            f'"{lesson_name}" was generated and saved to "{fb_path}".'
        )
        with open(fb_path, "rb") as file:
            return file.read()

    def _is_notebook_valid(
        self, path: str, lesson_name: str, notebook_name: str
    ) -> bool:
        """Validate the notebook.

        Args:
            path: Path to the notebook.
            lesson_name: Name of the lesson.
            notebook_name: Name of the notebook.

        Returns:
            True if the notebook is valid, False otherwise.
        """
        nb_cells: list[str] = []
        notebook_path = os.path.join(path, f"{notebook_name}.ipynb")
        try:
            # Get all cells
            with open(notebook_path, encoding="utf-8") as file:
                all_cells = json.load(file).get("cells", [])

            # Get only nbgrader cells
            nb_cells.extend(
                cell["metadata"]["nbgrader"].get("grade_id")
                for cell in all_cells
                if "nbgrader" in cell["metadata"]
            )
            logger.debug(f'The file "{notebook_path}" was loaded and parsed.')
        except (JSONDecodeError, UnicodeDecodeError):
            logger.debug(f'The file "{notebook_path}" does not have a json structure.')
            return False

        # Get valid cells
        with self._nb_grader.gradebook as gb:
            origin_cells = gb.find_notebook(notebook_name, lesson_name).source_cells
            logger.debug(f'Source cells of the notebook "{notebook_name}" were loaded.')
        true_cells = [cell.name for cell in origin_cells]
        return Counter(nb_cells) == Counter(true_cells)

    def _is_submission_newer(self, submitted_path: str, timestamp: datetime) -> bool:
        """Check if the submission is newer than the existing one.

        Args:
            submitted_path: Path to the existing submission.
            timestamp: Timestamp of the new submission.

        Returns:
            True if the submission is new, False otherwise.
        """
        path_timestamp = os.path.join(submitted_path, "timestamp.txt")

        # If there is no such path, the submission is the first
        if not os.path.exists(path_timestamp):
            logger.debug("It is the first submission of the user for this lesson.")
            return True

        # Read the old timestamp and compare with the new one
        with open(path_timestamp) as file:
            time_file = file.readline().strip()
            logger.debug("The previous submission was loaded.")
        time_old = parser.parse(time_file)
        return timestamp > time_old

    def _get_submission_grades(
        self, lesson_name: str, notebook_name: str, user_id: str
    ) -> list[Task]:
        """Get grades for the autograded submission.

        Args:
            lesson_name: Name of the lesson.
            notebook_name: Name of the notebook.
            user_id: User ID.

        Returns:
            Grades per each task.
        """
        # Get grades
        grades = {}
        with self._nb_grader.gradebook as gb:
            assignment = gb.find_submission(lesson_name, user_id)
            submission = assignment.notebooks[0]
            logger.debug("Notebook of the submission was loaded from the database.")
            for grade in submission.grades:
                grades[grade.name] = (grade.score, grade.max_score)

        # Get tasks description
        tasks = self._get_lesson_tasks(lesson_name, notebook_name)
        for task in tasks:
            task.score, task.max_score = grades[task.test_cell]
        logger.debug(
            f'Grades of the user "{user_id}" '
            f'for the lesson "{lesson_name}" were extracted.'
        )
        return tasks

    def _get_lesson_tasks(self, lesson_name: str, notebook_name: str) -> list[Task]:
        """Get task description for each test cell.

        It is assumed that only one test cell can be in each task.

        Args:
            lesson_name: Name of the lesson.
            notebook_name: Name of the notebook.

        Returns:
            Tasks in the right order.
        """
        # Load original assignment
        path_notebook = os.path.join("source", lesson_name, f"{notebook_name}.ipynb")
        with open(path_notebook, encoding="utf-8") as file:
            notebook = json.load(file)
            logger.debug(f'The notebook "{notebook_name}" was loaded from the source.')

        # Extract grade names
        pat = re.compile(TASK_NAME_PATTERN)
        tasks: list[Task] = []
        task = None
        for cell in notebook["cells"]:
            nb_data = cell["metadata"].get("nbgrader")
            if nb_data:
                # If it is a task name cell
                if cell["cell_type"] == "markdown":
                    is_todo = re.match(pat, cell["source"][0])
                    if is_todo:
                        task = Task(name=is_todo["name"])
                    continue

                # If it is a test cell
                if (
                    cell["cell_type"] == "code"
                    and nb_data["grade"]
                    and task is not None
                ):
                    task.test_cell = nb_data["grade_id"]
                    tasks.append(task)
        logger.debug(f'Parsed "{len(tasks)}" tasks from the lesson "{lesson_name}".')
        return tasks

    def stop(self) -> None:
        """Stop grading."""
        self._db.stop_db_connection()
        logger.debug("Grader was stopped.")

    def _check_schema(self) -> None:
        """Check if all the necessary tables exist."""
        # Standard nbgrader schema
        with self._nb_grader.gradebook as gb:
            course_id = self._config.CourseDirectory.course_id
            gb.check_course(course_id)
            logger.debug("Standard nbgrader schema was checked.")

        # Customizationsa
        alembic_cfg = alembic.config.Config()
        alembic_cfg.set_main_option("script_location", "alembic")

        # TODO: Check the version of db schema
        alembic.command.upgrade(alembic_cfg, "head")
        logger.debug("Database schema was actualized by alembic.")
        self._db.refresh_metadata()

    def _get_notebook_name(self, lesson_name: str) -> str | None:
        """Get name of the notebook for particular lesson.

        It is assumed there is only one notebook per lesson.

        Args:
            lesson_name: Name of the lesson.

        Returns:
            Notebook name.
        """
        with self._nb_grader.gradebook as gb:
            names = [n.name for n in gb.find_assignment(lesson_name).notebooks]
            logger.debug(f'Found {len(names)} notebooks of the lesson "{lesson_name}".')
            return names[0] if names else None
