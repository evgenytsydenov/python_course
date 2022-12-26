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

        Args:
            db_url: Database url.
        """
        self._engine = create_engine(db_url, pool_recycle=3600)
        self._meta = MetaData(bind=self._engine)
        self.refresh_metadata()

    def log_submission(
        self,
        submission_id: str,
        user_id: str,
        lesson_name: str,
        task_grades: list[Task],
        timestamp: datetime.datetime,
        standard_feedback: bytes,
        notebook: bytes,
    ) -> None:
        """Log submission information to the database.

        Args:
            submission_id: Submission id.
            user_id: User id.
            lesson_name: Lesson name.
            task_grades: Grades per task.
            timestamp: Submission timestamp.
            standard_feedback: Standard feedback.
            notebook: Submitted notebook.
        """
        # For the first start
        if "submission_logs" not in self._meta.tables:
            self._create_submission_log_table()

        with self._engine.connect() as connection:
            log_table = self._meta.tables["submission_logs"]
            ins = log_table.insert().values(
                submission_id=submission_id,
                user_id=user_id,
                submitted_notebook=notebook,
                lesson_name=lesson_name,
                task_grades=str(task_grades),
                timestamp=timestamp,
                feedback_standard=standard_feedback,
            )
            connection.execute(ins)
            logger.debug(
                f'Submission with the id "{submission_id}" was saved '
                f'to the "submission_logs" table.'
            )

    def get_lesson_info(self, lesson_name: str) -> dict[str, Any]:
        """Get information about the lesson.

        Args:
            lesson_name: Lesson name.

        Returns:
            Information about the lesson.
        """
        with self._engine.connect() as connection:
            les_tab = self._meta.tables["assignment"]
            q_filter = func.lower(les_tab.c.name) == lesson_name.lower()
            lesson_sql = select(["*"]).where(q_filter)
            result = connection.execute(lesson_sql).first()
            les_info = dict(result) if result else {}
            logger.debug(
                f'The information about the lesson "{lesson_name}" was loaded.'
            )
            return les_info

    def get_user_info(self, email: str) -> dict[str, Any]:
        """Get information about the user by email.

        Args:
            email: User's email.

        Returns:
            Dict with first name, last name, and email if the user exists,
                empty dict otherwise.
        """
        with self._engine.connect() as connection:
            users_table = self._meta.tables["student"]
            q_filter = func.lower(users_table.c.email) == email.lower()
            user_sql = select(["*"]).where(q_filter)
            result = connection.execute(user_sql).first()
            user_info = dict(result) if result else {}
            logger.debug(
                f'The information about the user with the email "{email}" was loaded.'
            )
            return user_info

    def _create_submission_log_table(self) -> None:
        """Create table to log submissions if it does not exist."""
        new_table = Table(
            "submission_logs",
            self._meta,
            Column("timestamp", DateTime, nullable=False),
            Column("submission_id", Text, nullable=False),
            Column("user_id", Text, nullable=False),
            Column("lesson_name", Text, nullable=False),
            Column("task_grades", Text, nullable=False),
            Column("submitted_notebook", LargeBinary(length=1e9), nullable=False),
            Column("feedback_standard", LargeBinary(length=1e9), nullable=False),
        )
        new_table.create(bind=self._engine)
        logger.debug('The table "submission_logs" was created.')
        self.refresh_metadata()

    def stop_db_connection(self) -> None:
        """Close all database connections."""
        self._engine.dispose()
        logger.debug("Database engine was disposed.")

    def is_db_empty(self) -> bool:
        """Check if the database empty.

        Returns:
            True if empty, False otherwise.
        """
        tables = self._engine.table_names()
        logger.debug("List of tables from the database was loaded.")
        return not tables

    def refresh_metadata(self) -> None:
        """Refresh metadata when database is modified from the outside."""
        self._meta.reflect()
        logger.debug("Database metadata was reloaded.")
