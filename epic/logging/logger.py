import logging
import inspect
from pathlib import Path

LogLevel = str | int


def get_logger(name: str | None = None, level: LogLevel = logging.NOTSET, *handlers: logging.Handler) -> logging.Logger:
    """
    Get the logger with the specified name, creating it if necessary.
    If a name is not specified, a logger appropriate for the context is returned:
        - If called at the module level, the module name is used.
        - If called inside a function, the function name is used.

    Parameters
    ----------
    name : str, optional
        The name of the logger to return or create.
        If not specified, the name will be chosen based on the module or function in which `get_logger` was called.

    level : str or int, default NOTSET
        Logging level for the log.

    *handlers : Handler
        Optional Handler objects to add to the logger.
        If any are provided, any handlers already attached to the logger (if it already exists) are removed first.

    Returns
    -------
    Logger
        Retrieved or created Logger object.
    """
    if name is None:
        try:
            caller_frame = inspect.currentframe().f_back
            module_name = getattr(inspect.getmodule(caller_frame), '__name__', None)
            func_name = inspect.getframeinfo(caller_frame).function
        finally:
            # make sure the frame reference is released explicitly to break any reference cycle
            del caller_frame
        if func_name == '<module>':
            func_name = None
        name = f'{module_name}.{func_name}' if module_name and func_name else module_name or func_name or '<default>'
    logger = logging.getLogger(name)
    if handlers:
        logger.handlers = []
        for h in handlers:
            logger.addHandler(h)
    elif not logger.hasHandlers():
        logger.addHandler(logging.NullHandler())
    logger.setLevel(level)
    return logger


class ClassLogger:
    """
    Create a class member that provides a logger for a class using the class' name as sub-logger name.
    This is meant to be called inside a class definition.

    Parameters
    ----------
    parent_logger : Logger, optional
        The created logger will be a child of this logger.
        If not provided, the parent logger will have the name of the module containing the class.

    Examples
    --------
    In file mymodule.py:
    >>> class MyClass:
    ...     logger = ClassLogger()
    ...     # more implementation

    Both methods and classmethods can use the class logger, and its name is "mymodule.MyClass".
    """
    def __init__(self, parent_logger: logging.Logger | None = None):
        self.parent = parent_logger

    def __get__(self, obj, obj_class: type) -> logging.Logger:
        parent = get_logger(obj_class.__module__) if self.parent is None else self.parent
        return parent.getChild(obj_class.__name__)


def _get_preconfigured_logger(name: str, level: LogLevel, *handlers: logging.Handler) -> logging.Logger:
    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
    return get_logger(name, level, *handlers)


def get_console_logger(name: str, level: LogLevel = logging.INFO) -> logging.Logger:
    """
    Get a logger pre-configured to print to the console.

    Parameters
    ----------
    name : str
        Name of the logger.

    level : str or int, default INFO
        Logging level for the log.

    Returns
    -------
    Logger
    """
    return _get_preconfigured_logger(name, level, logging.StreamHandler())


def get_file_logger(name: str, filename: str | Path, mode: str = 'a', level: LogLevel = logging.INFO) -> logging.Logger:
    """
    Get a logger pre-configured to write to a file.

    Parameters
    ----------
    name : str
        Name of the logger.

    filename : str or Path
        Name of the file to write to.

    mode : str, default 'a'
        File writing mode.

    level : str or int, default INFO
        Logging level for the log.

    Returns
    -------
    Logger
    """
    return _get_preconfigured_logger(name, level, logging.FileHandler(filename=filename, mode=mode))


def get_file_and_console_logger(name: str, filename: str | Path, mode: str = 'a',
                                level: LogLevel = logging.INFO) -> logging.Logger:
    """
    Get a logger pre-configured to write to a file and also print to the console.

    Parameters
    ----------
    name : str
        Name of the logger.

    filename : str or Path
        Name of the file to write to.

    mode : str, default 'a'
        File writing mode.

    level : str or int, default INFO
        Logging level for the log.

    Returns
    -------
    Logger
    """
    return _get_preconfigured_logger(
        name, level, logging.FileHandler(filename=filename, mode=mode), logging.StreamHandler(),
    )
