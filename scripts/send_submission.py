import os

from dotenv import load_dotenv

from definitions import ROOT_PATH
from utils.smtp_sender import SMTPSender

load_dotenv()

if __name__ == "__main__":
    lessons = []
    if not lessons:
        lessons = os.listdir(os.path.join(ROOT_PATH, "release"))

    smtp = SMTPSender(
        login=os.environ["TEST_USER_SMTP_LOGIN"],
        password=os.environ["TEST_USER_SMTP_PASSWORD"],
        server=os.environ["TEST_USER_SMTP_SERVER"],
        server_port=os.environ["TEST_USER_SMTP_PORT"],
    )
    for lesson in lessons:
        file_path = os.path.join(ROOT_PATH, "source", lesson, f"{lesson}.ipynb")
        smtp.send(
            destination=os.environ["GMAIL_FETCH_ALIAS"],
            subject=f'{os.environ["GMAIL_FETCH_KEYWORD"]} / {lesson}',
            files=[file_path],
        )
