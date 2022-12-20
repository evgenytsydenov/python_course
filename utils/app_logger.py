import logging
import logging.handlers
import os
from datetime import datetime

import pytz

from definitions import DATE_FORMAT, LOG_FORMAT_DEBUG, LOG_FORMAT_INFO, ROOT_PATH


class CustomFormatter(logging.Formatter):
    """Override standard Formatter to specify timezone."""

    def converter(self, timestamp: float) -> datetime:
        """Convert time to UTC zone.

        :param timestamp: time in seconds.
        :return: datetime object in UTC zone.
        """
        dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
        return dt.astimezone(pytz.timezone("UTC"))

    def formatTime(  # noqa N802
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """Convert time to specified format.

        :param record: log record.
        :param datefmt: date format.
        :return: time in string format.
        """
        dt = self.converter(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def _get_file_handler(path: str) -> logging.FileHandler:
    """Create logger to save logs to a file.

    :param path: path to log file.
    :return: file handler for logs.
    """
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        CustomFormatter(fmt=LOG_FORMAT_DEBUG, datefmt=DATE_FORMAT)
    )
    return file_handler


def _get_stream_handler() -> logging.StreamHandler:
    """Create logger to print logs to console.

    :return: stream handler for logs.
    """
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(
        CustomFormatter(fmt=LOG_FORMAT_INFO, datefmt=DATE_FORMAT)
    )
    return stream_handler


def get_logger(module_name: str, log_file_name: str = "system.log") -> logging.Logger:
    """Create logger.

    :param log_file_name: name of the log file.
    :param module_name: name of the module where events happen.
    :return: logger.
    """
    logger = logging.getLogger(module_name)
    path_logs = os.path.join(ROOT_PATH, "logs")
    logger.setLevel(logging.DEBUG)
    if not os.path.exists(path_logs):
        os.mkdir(path_logs)
    logger.addHandler(_get_file_handler(os.path.join(path_logs, log_file_name)))
    logger.addHandler(_get_stream_handler())
    return logger
