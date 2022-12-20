import datetime
from dataclasses import dataclass, field
from enum import Enum

from definitions import DATE_FORMAT


@dataclass
class Submission:
    """Submission parameters."""

    # Submission timestamp
    timestamp: datetime.datetime

    # Path where submission files were saved
    filepath: str

    # Submission id from exchanger
    exchange_id: str

    # Lesson name
    lesson_name: str
    _lesson_name: str = field(init=False, repr=False, default="")

    # User's email
    email: str
    _email: str = field(init=False, repr=False, default="")

    @property
    def email(self) -> str:
        """User's email."""
        return self._email

    @email.setter
    def email(self, email: str) -> None:
        """Normalize email address."""
        self._email = email.strip()

    @property
    def lesson_name(self) -> str:
        """Lesson name."""
        return self._lesson_name

    @lesson_name.setter
    def lesson_name(self, lesson_name: str) -> None:
        """Clean lesson name."""
        self._lesson_name = lesson_name.strip()

    def __str__(self) -> str:
        return (
            f"Timestamp: {self.timestamp.strftime(DATE_FORMAT)}, "
            f"Email: {self.email}, "
            f"Lesson name: {self.lesson_name}, "
            f"Submission ID: {self.exchange_id}"
        )


@dataclass
class Task:
    """Task description."""

    # Name of the task from assignment
    name: str

    # Max score for the task
    max_score: float = 0

    # Current score for the task
    score: float = 0

    # Name of test cell
    test_cell: str | None = None

    def __str__(self) -> str:
        return (
            f"Task name: {self.name}, "
            f"Current score: {self.score}, "
            f"Max score: {self.max_score}, "
            f"Name of test cell: {self.test_cell}"
        )


class GradeStatus(Enum):
    """Status of grading process."""

    SUCCESS = 0
    ERROR_USERNAME_IS_ABSENT = 1
    ERROR_NO_CORRECT_FILES = 2
    ERROR_LESSON_IS_ABSENT = 3
    ERROR_NOTEBOOK_CORRUPTED = 4
    ERROR_GRADER_FAILED = 5
    SKIPPED = 6


@dataclass
class GradeResult:
    """Grade results parameters."""

    # Status of grading process
    status: GradeStatus

    # Submission info
    timestamp: datetime.datetime

    # User info
    email: str
    student_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    # Lesson info
    lesson_name: str | None = None
    due_date: datetime.datetime | None = None

    # Grades per each task
    task_grades: list[Task] | None = None


@dataclass
class Feedback:
    """Feedback information."""

    email: str
    subject: str
    html_body: str
    student_name: str | None = None
