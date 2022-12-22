import datetime
from dataclasses import dataclass
from enum import Enum


@dataclass
class Submission:
    """Submission parameters.

    Attributes:
        timestamp: Submission timestamp.
        file_path: Path where the submission files were saved.
        submission_id: Submission id.
        lesson_name: Name of the lesson.
        email: User's email.
    """

    timestamp: datetime.datetime
    file_path: str
    submission_id: str
    lesson_name: str
    email: str


@dataclass
class Task:
    """Task description.

    Attributes:
        name: Name of the task from the assignment.
        max_score: Max score for the task.
        score: Current score for the task.
        test_cell: Name of the test cell.
    """

    name: str
    max_score: float = 0
    score: float = 0
    test_cell: str | None = None


class GradeStatus(Enum):
    """Status of the grading process."""

    SUCCESS = 0
    ERROR_USERNAME_IS_ABSENT = 1
    ERROR_NO_CORRECT_FILES = 2
    ERROR_LESSON_IS_ABSENT = 3
    ERROR_NOTEBOOK_CORRUPTED = 4
    ERROR_GRADER_FAILED = 5
    SKIPPED = 6


@dataclass
class GradeResult:
    """Grade results parameters.

    Attributes:
        status: Status of the grading process.
        timestamp: Timestamp of the submission.
        email: Email of the student.
        student_id: ID of the student.
        first_name: Name of the student.
        last_name: Surname of the student.
        lesson_name: Name of the lesson.
        task_grades: Grades per each task.
    """

    status: GradeStatus
    timestamp: datetime.datetime
    email: str
    student_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    lesson_name: str | None = None
    task_grades: list[Task] | None = None


@dataclass
class Feedback:
    """Feedback information.

    Attributes:
        email: Email to send.
        subject: Subject of the email.
        html_body: Feedback content.
        student_name: Name of the student to insert into the feedback.
    """

    email: str
    subject: str
    html_body: str
    student_name: str | None = None
