import os

from definitions import DATE_FORMAT, ROOT_PATH
from utils.app_logger import get_logger
from utils.data_models import Feedback, GradeResult, GradeStatus, Task

logger = get_logger(__name__)


class FeedbackCreator:
    """Create feedbacks for users."""

    def __init__(
        self, course_name: str, teacher_email: str, picture_links: dict[str, str]
    ) -> None:
        """Feedback maker.

        Args:
            course_name: Name of the course.
            teacher_email: Teacher's email.
            picture_links: Links to the pictures uploaded to a cloud folder.
        """
        self._teacher_email = teacher_email
        self._course_name = course_name
        self._pics = picture_links
        self._template_path = os.path.join(ROOT_PATH, "exchanger", "resources")
        self._template = self._load_template("template.html")
        self._styles = self._load_template("styles.css")
        self._error_body = self._load_template("error_body.html")
        self._grades_body = self._load_template("grades_body.html")
        logger.info("Feedback creator started successfully.")

    def get_feedback(self, grade_result: GradeResult) -> Feedback:
        """Create feedback after grading.

        Args:
            grade_result: Result of the grading.

        Returns:
            Feedback.
        """
        if grade_result.status is GradeStatus.ERROR_NO_CORRECT_FILES:
            body, subject = self._get_no_correct_files_feedback()
        elif grade_result.status is GradeStatus.ERROR_NOTEBOOK_CORRUPTED:
            body, subject = self._get_notebook_corrupted_feedback()
        elif grade_result.status is GradeStatus.ERROR_LESSON_IS_ABSENT:
            body, subject = self._get_incorrect_lesson_feedback()
        elif grade_result.status is GradeStatus.ERROR_USERNAME_IS_ABSENT:
            body, subject = self._get_absent_username_feedback()
        elif grade_result.status is GradeStatus.ERROR_GRADER_FAILED:
            body, subject = self._get_grader_failed_feedback()
        elif grade_result.status is GradeStatus.SUCCESS:
            body, subject = self._get_success_feedback(grade_result)
        else:
            raise ValueError(f'Unknown grade status "{grade_result.status}".')
        content = self._template.format(
            styles=self._styles,
            body=body,
            course_icon=self._pics["course_icon"],
            course_name=self._course_name,
        )

        student_name = None
        if grade_result.first_name and grade_result.last_name:
            student_name = f"{grade_result.first_name} {grade_result.last_name}"
        feedback = Feedback(
            submission_id=grade_result.submission_id,
            subject=subject,
            html_body=content,
            email=grade_result.email,
            student_name=student_name,
        )

        logger.info(
            f"Feedback for the submission "
            f'with the id "{feedback.submission_id}" was created.'
        )
        return feedback

    def _get_success_feedback(self, grade_result: GradeResult) -> tuple[str, str]:
        """Create feedback when the grading process was successful.

        Args:
            grade_result: Result of the grading.

        Returns:
            The body and subject of the message.
        """
        if (
            (not grade_result.lesson_name)
            or (not grade_result.task_grades)
            or (not grade_result.first_name)
        ):
            raise ValueError("Obligatory values are missed.")
        timestamp = grade_result.timestamp.strftime(DATE_FORMAT)
        subject = f"{self._course_name} / {grade_result.lesson_name} / {timestamp}"
        score = sum(task.score for task in grade_result.task_grades)
        max_score = sum(task.max_score for task in grade_result.task_grades)
        body = self._grades_body.format(
            first_name=grade_result.first_name,
            lesson_name=grade_result.lesson_name,
            grades_info=self._get_grade_part(grade_result.task_grades),
            image_link=self._get_pic_by_grade(score),
            team_speech=self._get_feedback_message(score, max_score),
            sum_score=round(score, 1),
        )
        logger.debug("The feedback for the case of successful grading was created.")
        return body, subject

    def _get_pic_by_grade(self, grade_sum: float) -> str:
        """Find picture according to the grade.

        Args:
            grade_sum: Sum of grades for the lesson.

        Returns:
            Picture in string format.
        """
        if grade_sum <= 20:
            return self._pics["0_20"]
        if grade_sum <= 40:
            return self._pics["21_40"]
        if grade_sum <= 60:
            return self._pics["41_60"]
        if grade_sum <= 80:
            return self._pics["61_80"]
        if grade_sum <= 99:
            return self._pics["81_99"]
        if grade_sum == 100:
            return self._pics["100"]
        raise ValueError(f'Unknown value of grade sum "{grade_sum}"')

    def _get_absent_username_feedback(self) -> tuple[str, str]:
        """Create feedback when the user is unknown.

        Returns:
            The body and subject of the message.
        """
        err_text = """
                   We have received your letter, but we do not know what to 
                   do with it. Your email is not in our database, 
                   so we cannot check the work.
                   """
        subject = f"{self._course_name} / Unknown user"
        body = self._error_body.format(
            err_text=err_text,
            teacher_email=self._teacher_email,
            image_link=self._pics["unknown_user"],
        )
        logger.debug("The feedback for the case of absent username was created.")
        return body, subject

    def _get_grader_failed_feedback(self) -> tuple[str, str]:
        """Create feedback when the grader failed during submission testing.

        Returns:
            The body and subject of the message.
        """
        err_text = """
                   We received your work, but the grading process ended 
                   with an error. Probably your code consumes too much RAM, 
                   has infinite loops, or contains very deep recursions.
                   Check it and send again :)
                   """
        subject = f"{self._course_name} / Grader failed"
        body = self._error_body.format(
            err_text=err_text,
            teacher_email=self._teacher_email,
            image_link=self._pics["grader_failed"],
        )
        logger.debug("The feedback for the case of grader failing was created.")
        return body, subject

    def _get_incorrect_lesson_feedback(self) -> tuple[str, str]:
        """Create feedback when the lesson name of submission is unknown.

        Returns:
            The body and subject of the message.
        """
        err_text = """
                   We have received your submission, but the lesson name 
                   extracted from the email subject is not correct. 
                   Check it and send again :)
                   """
        subject = f"{self._course_name} / Unknown lesson"
        body = self._error_body.format(
            err_text=err_text,
            teacher_email=self._teacher_email,
            image_link=self._pics["unknown_lesson"],
        )
        logger.debug("The feedback for the case of incorrect lesson name was created.")
        return body, subject

    def _get_no_correct_files_feedback(self) -> tuple[str, str]:
        """Create feedback when the submission does not contain correct files.

        Returns:
            The body and subject of the message.
        """
        err_text = """
                   We have received your submission, but we have not found any 
                   files that are necessary for the lesson specified in the 
                   subject. Check the files and send again :)
                   """
        subject = f"{self._course_name} / No correct files"
        body = self._error_body.format(
            err_text=err_text,
            teacher_email=self._teacher_email,
            image_link=self._pics["unknown_files"],
        )
        logger.debug("The feedback for the case of no correct files was created.")
        return body, subject

    def _get_notebook_corrupted_feedback(self) -> tuple[str, str]:
        """Create feedback.

        For the case when the content of the notebook does not correspond to the lesson.

        Returns:
            The body and subject of the message.
        """
        err_text = """
                   We have received your submission and found necessary 
                   files in the attachment. However, our robots are confused :) 
                   Because the content of the files does not match the lesson 
                   specified in the subject.
                   """
        subject = f"{self._course_name} / Robots in panic"
        body = self._error_body.format(
            err_text=err_text,
            teacher_email=self._teacher_email,
            image_link=self._pics["unknown_content"],
        )
        logger.debug("The feedback for the case of corrupted notebooks was created.")
        return body, subject

    def _get_grade_part(self, grades: list[Task]) -> str:
        """Get HTML part of the grade info.

        Args:
            grades: Grades and their names.

        Returns:
            HTML part in string format.
        """
        grades_part = ""
        for index, task in enumerate(grades):
            img = self._pics["check"]
            if task.score < task.max_score:
                img = self._pics["xmark"]
            grades_part += f"""
            <tr>
                <td>{index + 1}. {task.name}</td>
                <td>{round(task.score, 1)}</td>
                <td><img class="report-table-icon" 
                src="{img}" alt="Mark" style="border: none; 
                -ms-interpolation-mode: bicubic; display: block; 
                width: 14px; height: 14px;" width="14" height="14"></td>
            </tr>
            """
        logger.debug("Grade part of the feedback was created.")
        return grades_part

    def _get_feedback_message(self, score: float, max_score: float) -> str:
        """Create feedback message.

        Args:
            score: Grade score.
            max_score: Max grade score.

        Returns:
            Message.
        """
        if score == 0:
            return """
            It seems that something went wrong, and the tasks were not solved. 
            Try again to study the theory and reread task descriptions.<br>
            We also recommend you use the links to additional materials. 
            Don't be discouraged - everyone makes mistakes. 
            We look forward to getting more letters from you.
            """

        if score <= 80:
            return f"""
            You scored {round(score, 0)} out of {round(max_score, 0)} points, 
            which is not enough for the lesson to be passed. Try again to study 
            the theory and reread task descriptions.<br>
            We also recommend you use the links to additional materials. 
            Don't be discouraged - everyone makes mistakes. 
            We look forward to getting more letters from you.
            """

        if score <= 99:
            return f"""It looks like you have a good understanding of the 
            topic and scored {round(score, 0)} out of 
            {round(max_score, 0)} points. 
            The result is accepted, and you can proceed to the next lesson.<br>
            If you want to bring the result to perfection, 
            find your mistakes and send the solution again. 
            We also recommend you look at additional materials. 
            Perhaps you will discover something new for yourself.
            """

        if score == 100:
            return """Excellent! You have reached the maximum number of 
            points.The result is accepted, and you can proceed to the next 
            lesson.<br> 
            If you want to understand the topic even better, 
            we advise you to look at additional materials. Perhaps you will 
            discover something new for yourself."""
        raise ValueError(f"Unspecified condition for {score}.")

    def _load_template(self, name: str) -> str:
        """Load template files.

        Args:
            name: Name of the template.

        Returns:
            Template content.
        """
        template_path = os.path.join(self._template_path, name)
        with open(template_path, encoding="utf-8") as file:
            content = file.read()
            logger.debug(f'The feedback template "{template_path}" was loaded.')
            return content
