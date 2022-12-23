import logging
import logging.handlers
import os
import time
import typing
from datetime import datetime
from time import struct_time

import pytz

from definitions import DATE_FORMAT, LOG_FORMAT_DEBUG, LOG_FORMAT_INFO, ROOT_PATH


class CustomFormatter(logging.Formatter):
    """Override standard Formatter to specify timezone."""

    def converter(self, timestamp: float | None) -> struct_time:
        """Get structured UTC time from the timestamp.

        Args:
            timestamp: Time in seconds.

        Returns:
            Structured time object.
        """
        return time.gmtime(timestamp)

    def formatTime(  # noqa N802
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """Convert time to the specified format.

        Args:
            record: Log record.
            datefmt: Date format.

        Returns:
            Time in string format.
        """
        struct_dt_utc = self.converter(record.created)
        dt = datetime(*struct_dt_utc[:6], tzinfo=pytz.UTC)
        return dt.strftime(datefmt) if datefmt else dt.isoformat()


def _get_file_handler(path: str) -> logging.FileHandler:
    """Create logger to save logs to a file.

    Args:
        path: Path to log file.

    Returns:
        File handler for logs.
    """
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        CustomFormatter(fmt=LOG_FORMAT_DEBUG, datefmt=DATE_FORMAT)
    )
    return file_handler


def _get_stream_handler() -> logging.StreamHandler[typing.TextIO]:
    """Create logger to print logs to the console.

    Returns:
        Stream handler for logs.
    """
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(
        CustomFormatter(fmt=LOG_FORMAT_INFO, datefmt=DATE_FORMAT)
    )
    return stream_handler


def get_logger(module_name: str, log_file_name: str = "system.log") -> logging.Logger:
    """Create logger.

    Args:
        module_name: Name of the log file.
        log_file_name: Name of the module where events happen.

    Returns:
        Logger.
    """
    path_logs = os.path.join(ROOT_PATH, "logs")
    if not os.path.exists(path_logs):
        os.mkdir(path_logs)
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(_get_file_handler(os.path.join(path_logs, log_file_name)))
    logger.addHandler(_get_stream_handler())
    return logger
