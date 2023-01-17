from .logger import (
    LogLevel,
    ClassLogger,
    get_logger,
    get_console_logger,
    get_file_logger,
    get_file_and_console_logger,
)

from .logregator import Logregator, Logtor

# Default instance
class_logger = ClassLogger()
