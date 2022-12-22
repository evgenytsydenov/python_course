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
from definitions import DATE_FORMAT, ROOT_PATH, TASK_NAME_PATTERN
from grader.database import DatabaseHandler
from utils.app_logger import get_logger
from utils.data_models import GradeResult, GradeStatus, Submission, Task

logger = get_logger(__name__)


class Grader:
    """Grader class."""

    def __init__(self, grader_config: Config) -> None:
        """Create grader.

        :param grader_config: grader configuration.
        """
        self._config = grader_config
        self._db = DatabaseHandler(self._config.CourseDirectory.db_url)
        self._nb_grader = NbGraderAPI(config=self._config)
        self._check_schema()
        logger.info("Grader started successfully.")

    def grade_submission(self, submission: Submission) -> GradeResult:
        """Grade submission.

        At first, this will check submission parameters (user id, lesson name,
        etc). If they are correct, the submission will be graded.

        :param submission: submission.
        :return: grading result.
        """
        logger.info(f"Start grading the submission: {submission}.")
        grade_result = GradeResult(
            status=GradeStatus.SUCCESS,
            timestamp=submission.timestamp,
            email=submission.email,
        )

        # Get user information
        user_info = self._db.get_user_info(submission.email)
        if not user_info:
            logger.info(
                f"The information about user with "
                f'email "{submission.email}" was not found.'
            )
            grade_result.status = GradeStatus.ERROR_USERNAME_IS_ABSENT
            shutil.rmtree(submission.file_path)
            logger.debug(
                f'Data of submission "{submission.submission_id} was '
                f'dropped from downloaded folder."'
            )
            return grade_result
        user_ = user_info["id"]
        grade_result.email = user_info["email"]
        grade_result.student_id = user_info["id"]
        grade_result.first_name = user_info["first_name"]
        grade_result.last_name = user_info["last_name"]

        # Get lesson information
        lesson_info = self._db.get_lesson_info(submission.lesson_name)
        if not lesson_info:
            logger.info(
                f"The information about lesson with name "
                f'"{submission.lesson_name}" was not found.'
            )
            grade_result.status = GradeStatus.ERROR_LESSON_IS_ABSENT
            shutil.rmtree(submission.file_path)
            logger.debug(
                f'Data of submission "{submission.submission_id} was '
                f'dropped from downloaded folder."'
            )
            return grade_result
        lesson_ = lesson_info["name"]
        grade_result.lesson_name = lesson_info["name"]
        grade_result.due_date = lesson_info["duedate"]

        # Check if the file for this lesson exists
        downloaded_path = os.path.join(submission.file_path, f"{lesson_}.ipynb")
        if not os.path.exists(downloaded_path):
            logger.info("The notebook for grading was not found among submitted files.")
            grade_result.status = GradeStatus.ERROR_NO_CORRECT_FILES
            shutil.rmtree(submission.file_path)
            logger.debug(
                f'Data of submission "{submission.submission_id} was '
                f'dropped from downloaded folder."'
            )
            return grade_result

        # Check if the submission is newer than the existing one
        submitted_path = os.path.join(ROOT_PATH, "submitted", user_, lesson_)
        if not self._is_submission_newer(submitted_path, submission.timestamp):
            logger.info("The submission is not newer than the existing one. Skip it.")
            grade_result.status = GradeStatus.SKIPPED
            shutil.rmtree(submission.file_path)
            logger.debug(
                f'Data of submission "{submission.submission_id} was '
                f'dropped from downloaded folder."'
            )
            return grade_result

        # Check the notebook structure
        if not self._is_notebook_valid(downloaded_path, lesson_):
            logger.info(
                f"Structure of the notebook " f'"{downloaded_path}" is corrupted.'
            )
            grade_result.status = GradeStatus.ERROR_NOTEBOOK_CORRUPTED
            shutil.rmtree(submission.file_path)
            logger.debug(
                f'Data of submission "{submission.submission_id} was '
                f'dropped from downloaded folder."'
            )
            return grade_result

        # Test the submission
        self._move_checked_files(
            submission.file_path, submitted_path, submission.timestamp
        )
        if not self._autograde(lesson_, user_):
            grade_result.status = GradeStatus.ERROR_GRADER_FAILED
            return grade_result
        grades = self._get_submission_grades(lesson_, user_)
        grade_result.task_grades = grades

        # Generate standard feedback
        feedback = self._create_nbgrader_feedback(lesson_, user_)

        # Save submission info to database
        with open(os.path.join(submitted_path, f"{lesson_}.ipynb"), "rb") as f:
            notebook = f.read()
        self._db.log_submission(
            user_, lesson_, grades, submission.timestamp, feedback, notebook
        )
        return grade_result

    def _move_checked_files(
        self, downloaded_path: str, submitted_path: str, timestamp: datetime
    ) -> None:
        """Move files from downloaded folder to submitted folder.

        :param downloaded_path: path to files in downloaded folder.
        :param submitted_path: path to files in submitted folder.
        :param timestamp: submission timestamp.
        """
        # Copy all files
        if os.path.exists(submitted_path):
            shutil.rmtree(submitted_path)
            logger.info(f'Submitted directory "{submitted_path}" was cleared.')
        shutil.copytree(downloaded_path, submitted_path)

        # Add timestamp information
        timestamp_path = os.path.join(submitted_path, "timestamp.txt")
        with open(timestamp_path, "w") as file:
            timestamp_str = timestamp.strftime(DATE_FORMAT)
            file.write(timestamp.strftime(DATE_FORMAT))
        logger.debug(
            f'Submission timestamp "{timestamp_str}" was written '
            f'to "{timestamp_path}".'
        )
        logger.info(f'Submission files were moved to "{submitted_path}".')

        # Remove files from downloaded folder
        shutil.rmtree(downloaded_path)
        logger.debug(f"Downloaded files were removed " f'from "{downloaded_path}".')

    def _autograde(self, lesson_name: str, user_id: str) -> bool:
        """Run autograding process.

        :param lesson_name: name of the lesson.
        :param user_id: user id.
        :return: if the autograding was successful.
        """
        logger.debug(
            f'Start autograding of user "{user_id}" for lesson "{lesson_name}.'
        )
        status = self._nb_grader.autograde(lesson_name, user_id, create=False)
        logs = re.sub(r"\[\w+\] ", "", status["log"]).replace("\n", ". ")
        logger.debug(f"Grader output: {logs}")
        if not status["success"]:
            logger.error(f'Traceback: {status.get("error")}')
            with self._nb_grader.gradebook as gb:
                gb.remove_submission(lesson_name, user_id)
                logger.debug(
                    f'Submission of user "{user_id}" for lesson '
                    f'"{lesson_name}" was removed from the database.'
                )
            path_ = os.path.join(ROOT_PATH, "submitted", user_id, lesson_name)
            if os.path.exists(path_):
                shutil.rmtree(path_)
                logger.debug(f'Submitted directory "{path_}" was cleared.')
            return False
        logger.info(
            f'Submission of user "{user_id}" for '
            f'lesson "{lesson_name}" was autograded.'
        )
        return True

    def _create_nbgrader_feedback(self, lesson_name: str, user_id: str) -> bytes:
        """Generate standard nbgrader feedback.

        :param lesson_name: name of the lesson.
        :param user_id: user id.
        :return: feedback content.
        """
        logger.debug(
            f"Start generating nbgrader feedback of user "
            f"{user_id} with lesson {lesson_name}."
        )
        status = self._nb_grader.generate_feedback(lesson_name, user_id)
        logs = re.sub(r"\[\w+\] ", "", status["log"]).replace("\n", ". ")
        if not status["success"]:
            logger.error(f"Grader output: {logs}")
            raise RuntimeError(
                f"Generating nbgrader feedback of user "
                f"{user_id} with lesson {lesson_name} failed."
            )
        logger.debug(f"Grader output: {logs}")
        fb_path = os.path.join(
            ROOT_PATH, "feedback", user_id, lesson_name, f"{lesson_name}.html"
        )
        logger.info(
            f'Nbgrader feedback of user "{user_id}" with lesson '
            f'"{lesson_name}" was generated and saved to "{fb_path}".'
        )
        with open(fb_path, "rb") as file:
            return file.read()

    def _is_notebook_valid(self, path: str, lesson_name: str) -> bool:
        """Validate notebook.

        Notebook is not valid when it does not contain solution cells.

        :param path: path to notebook.
        :param lesson_name: name of lesson.
        :return: True if notebook is valid, False otherwise.
        """
        nb_cells = []
        try:
            # Get all cells
            with open(path, encoding="utf-8") as file:
                all_cells = json.load(file).get("cells", [])

            # Get only nbgrader cells
            nb_cells.extend(
                cell["metadata"]["nbgrader"].get("grade_id")
                for cell in all_cells
                if "nbgrader" in cell["metadata"]
            )
        except (JSONDecodeError, UnicodeDecodeError):
            logger.debug(f'File "{path}" does not have a json structure.')
            return False

        # Get valid cells
        with self._nb_grader.gradebook as gb:
            origin_cells = gb.find_notebook(lesson_name, lesson_name).source_cells
        true_cells = [cell.name for cell in origin_cells]
        return Counter(nb_cells) == Counter(true_cells)

    def _is_submission_newer(self, submitted_path: str, timestamp: datetime) -> bool:
        """Check if the submission is newer than the existing one.

        :param timestamp: timestamp of the new submission.
        :param submitted_path: path to the existing submission.
        :return: True if the submission is new, False otherwise.
        """
        path_timestamp = os.path.join(submitted_path, "timestamp.txt")

        # If there is no such path, the submission is the first
        if not os.path.exists(path_timestamp):
            logger.debug("It is the first submission of the user for this lesson.")
            return True

        # Read the old timestamp and compare with the new one
        with open(path_timestamp) as file:
            time_old = file.readline().strip()
            logger.debug(f'The previous submission was made "{time_old}".')
        time_old = parser.parse(time_old)
        return timestamp > time_old

    def _get_submission_grades(self, lesson_name: str, user_id: str) -> list[Task]:
        """Get grades for autograded submission.

        :param lesson_name: name of the lesson.
        :param user_id: user id.
        :return: grades per each task.
        """
        # Get grades
        grades = {}
        with self._nb_grader.gradebook as gb:
            assignment = gb.find_submission(lesson_name, user_id)
            submission = assignment.notebooks[0]
            for grade in submission.grades:
                grades[grade.name] = (grade.score, grade.max_score)

        # Get tasks description
        tasks = self._get_lesson_tasks(lesson_name)
        for task in tasks:
            task.score, task.max_score = grades[task.test_cell]
        logger.debug(
            f'Grades of user "{user_id}" for lesson "{lesson_name}" were extracted.'
        )
        return tasks

    def _get_lesson_tasks(self, lesson_name: str) -> list[Task]:
        """Get task description for each test cell.

        It is assumed that only one test cell can be in each task.

        :param lesson_name: name of lesson.
        :return: tasks in the right order.
        """
        # Load original assignment
        path_notebook = os.path.join("source", lesson_name, f"{lesson_name}.ipynb")
        with open(path_notebook, encoding="utf-8") as file:
            notebook = json.load(file)

        # Extract grade names
        pat = re.compile(TASK_NAME_PATTERN)
        tasks = []
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
                if cell["cell_type"] == "code" and nb_data["grade"]:
                    task.test_cell = nb_data["grade_id"]
                    tasks.append(task)
        logger.debug(f'Task names were extracted for lesson "{lesson_name}".')
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

        # Customizations
        alembic_cfg = alembic.config.Config()
        alembic_cfg.set_main_option(
            "script_location", os.path.join(ROOT_PATH, "alembic")
        )
        alembic.command.upgrade(alembic_cfg, "head")
        self._db.refresh_metadata()
