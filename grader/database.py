import datetime
from typing import Any

from sqlalchemy import Column, DateTime, LargeBinary, MetaData, Table, Text, func
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import select

from utils.app_logger import get_logger
from utils.data_models import Task

logger = get_logger(__name__)


class DatabaseHandler:
    """Database handler."""

    def __init__(self, db_url: str) -> None:
        """Create database handler.

        :param db_url: database url.
        """
        self._engine = create_engine(db_url, pool_recycle=3600)
        self._meta = MetaData(bind=self._engine)
        self.refresh_metadata()

    def log_submission(
        self,
        user_name: str,
        lesson_name: str,
        task_grades: list[Task],
        timestamp: datetime,
        standard_feedback: bytes,
        notebook: bytes,
    ) -> None:
        """Log submission information to the database.

        :param notebook: submitted notebook.
        :param standard_feedback: standard feedback.
        :param user_name: user id.
        :param lesson_name: lesson name.
        :param task_grades: grades per task.
        :param timestamp: submission timestamp.
        """
        # For the first start
        if "submission_logs" not in self._meta.tables:
            self._create_submission_log_table()

        with self._engine.connect() as connection:
            log_table = self._meta.tables["submission_logs"]
            ins = log_table.insert().values(
                user_name=user_name,
                submitted_notebook=notebook,
                lesson_name=lesson_name,
                task_grades=str(task_grades),
                timestamp=timestamp,
                feedback_standard=standard_feedback,
            )
            connection.execute(ins)
            logger.debug(
                f'Submission of student "{user_name}" '
                f'for lesson "{lesson_name}" was saved '
                f'to the "submission_logs" table.'
            )

    def get_lesson_info(self, lesson_name: str) -> dict[str, Any]:
        """Get information about lesson.

        :param lesson_name: lesson name.
        :return: information about the lesson.
        """
        with self._engine.connect() as connection:
            les_tab = self._meta.tables["assignment"]
            q_filter = func.lower(les_tab.c.name) == lesson_name.lower()
            lesson_sql = select(["*"]).where(q_filter)
            result = connection.execute(lesson_sql).first()
            les_info = {}
            if result:
                les_info = dict(result)
            logger.debug(
                f"The following information about lesson with "
                f'name "{lesson_name}" was loaded: {les_info}.'
            )
            return les_info

    def get_user_info(self, email: str) -> dict[str, Any]:
        """Get information about user by email.

        :param email: user's email.
        :return: dict with first name, last name, and email if the user
        exists, empty dict otherwise.
        """
        with self._engine.connect() as connection:
            users_table = self._meta.tables["student"]
            q_filter = func.lower(users_table.c.email) == email.lower()
            user_sql = select(["*"]).where(q_filter)
            result = connection.execute(user_sql).first()
            user_info = {}
            if result:
                user_info = dict(result)
            logger.debug(
                f"The following information about user with "
                f'email "{email}" was loaded: {user_info}.'
            )
            return user_info

    def _create_submission_log_table(self) -> None:
        """Create table to log submissions if it does not exist."""
        new_table = Table(
            "submission_logs",
            self._meta,
            Column("timestamp", DateTime, nullable=False),
            Column("user_name", Text, nullable=False),
            Column("lesson_name", Text, nullable=False),
            Column("task_grades", Text, nullable=False),
            Column("submitted_notebook", LargeBinary(length=1e9), nullable=False),
            Column("feedback_standard", LargeBinary(length=1e9), nullable=False),
        )
        new_table.create(bind=self._engine)
        logger.debug('Table "submission_logs" was created.')
        self.refresh_metadata()

    def stop_db_connection(self) -> None:
        """Close all database connections."""
        self._engine.dispose()
        logger.debug("Database engine was disposed.")

    def is_db_empty(self) -> bool:
        """Check if database empty.

        :return: True if empty, False otherwise.
        """
        return not self._engine.table_names()

    def refresh_metadata(self) -> None:
        """Refresh metadata when database is modified from the outside."""
        self._meta.reflect()
        logger.debug("Database metadata loaded.")
