import os
import queue
import logging
import traceback
import threading
import multiprocessing as mp
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeVar

from epic.common.queue import IterableQueue

from .logger import get_console_logger, get_file_logger, get_file_and_console_logger, LogLevel


T = TypeVar("T")


class QueueLike(Protocol[T]):
    def put(self, obj: T) -> None: ...


class LogregatorHandler(logging.Handler):
    """
    A Handler that emits log records by putting them in a queue.
    Can install itself as a handler of the root logger, which ensures it is called for every
    log message which propagates in the current process or interpreter.

    Parameters
    ----------
    level : str or int, default NOTSET
        Logging level for the handler.

    output_queue : queue-like
        Destination of emitted records.
    """
    _MARK_OF_THE_LOGREGATOR = "__logregator"
    
    def __init__(self, level: LogLevel, output_queue: QueueLike[tuple[int, logging.LogRecord]]):
        super().__init__(level)
        self.output_queue = output_queue
        self._old_root_level = None

    def emit(self, record: logging.LogRecord) -> None:
        # Ignore these messages - they originate from a Logregator. Prevent cyclic logging!
        if self.is_handled(record):
            return
        if record.levelno >= self.level:
            # Note that we're already freely thread-safe and process-safe because of the Queue
            if record.exc_info is not None:
                record.exc_text = '\n'.join(traceback.format_exception(*record.exc_info))
                record.exc_info = None
            try:
                self.output_queue.put((os.getpid(), record))
            except queue.Full:
                # If the input queue was closed, suppress error
                pass

    def install(self) -> None:
        # Make sure we're installed only once
        if self in logging.root.handlers:
            return
        self._old_root_level = logging.root.level
        logging.root.setLevel(logging.NOTSET + 1)
        logging.root.addHandler(self)

    def uninstall(self) -> None:
        if self in logging.root.handlers:
            if self._old_root_level is None:
                raise RuntimeError("Cannot uninstall, LogregatorHandler was not properly installed.")
            logging.root.removeHandler(self)
            logging.root.setLevel(self._old_root_level)

    @classmethod
    def mark_as_handled(cls, record: logging.LogRecord) -> None:
        setattr(record, cls._MARK_OF_THE_LOGREGATOR, True)

    @classmethod
    def is_handled(cls, record: logging.LogRecord) -> bool:
        return getattr(record, cls._MARK_OF_THE_LOGREGATOR, False)


class LogregatorProcess(mp.context.SpawnProcess):
    """
    A subclass of SpawnProcess which collects any locally installed LogregatorHandlers and installs
    them on the remote process before running the main target function.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This is automagically transferred along with this entire instance via a socket when the process is started
        self._logregator_handlers = [
            (h.level, h.output_queue) for h in logging.root.handlers if isinstance(h, LogregatorHandler)
        ]

    def run(self):
        handlers = [LogregatorHandler(level, output_queue) for level, output_queue in self._logregator_handlers]
        for h in handlers:
            h.install()
        try:
            return super().run()
        finally:
            for h in handlers:
                h.uninstall()


class Logregator:
    """
    The consumer-side of the logging paradigm.
    Whenever the Logregator wraps any code (using the `with` statement), it automatically collects
    any log record emitted by any Logger, either locally or in a remote process created by the current process.

    Parameters
    ----------
    logger : Logger
         A logger into which this Logregator will redirect all the log records it intercepts.

    Notes
    -----
    Currently, intercepting log records from child processes only works for multiprocessing.Process.
    The joblib package works differently under the hood, and is currently not supported.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.my_pid = os.getpid()
        self._old_process: dict[mp.context.BaseContext | ModuleType, type[mp.process.BaseProcess] | None] = {
            mp.get_context("spawn"): None,
        }
        if mp.get_start_method() == "spawn":
            for ctx in (mp, mp.context):
                self._old_process[ctx] = None
        self._input_queue: IterableQueue[tuple[int, logging.LogRecord]] | None = None
        self._handler: LogregatorHandler | None = None
        self._consumer_thread: threading.Thread | None = None

    @property
    def started(self) -> bool:
        return self._consumer_thread is not None

    def _consume_logs_proc(self) -> None:
        assert self._input_queue is not None
        for pid, record in self._input_queue:
            # record is of type LogRecord - see logging/__init__.py
            # The handler should've filtered out records below our level, but make sure anyway.
            # Note that calling isEnabledFor is very cheap since it's cached inside the logger, apparently.
            if not self.logger.isEnabledFor(record.levelno):
                continue
            # Add some stuff to the message
            addendum = self.logger.name
            if self.my_pid != pid:
                addendum = f"{addendum} PID {pid}"
            elif record.name == self.logger.name:
                # For local logging, if the sink logger itself was the source of the record, there's no point in
                # propagating it again...
                continue
            record.msg = f"[{addendum}] - {record.msg}"
            # Send the record for processing in the sink logger - mark it as already handled locally, so that any
            # local LogeratorHandler ignores it instead of passing it on in an infinite loop.
            LogregatorHandler.mark_as_handled(record)
            self.logger.handle(record)

    def start(self) -> None:
        if not self.started:
            self._input_queue = IterableQueue("multiprocessing")
            self._handler = LogregatorHandler(self.logger.getEffectiveLevel(), self._input_queue)
            self._handler.install()
            # Ugly but effective
            for ctx in self._old_process:
                self._old_process[ctx] = ctx.Process
                ctx.Process = LogregatorProcess
            # Start the consumer thread in advance - it immediately blocks on the queue, so it doesn't cost anything
            try:
                self._consumer_thread = threading.Thread(target=self._consume_logs_proc)
                self._consumer_thread.daemon = True
                self._consumer_thread.start()
            except Exception:
                self._consumer_thread = None

    def stop(self) -> None:
        if self.started:
            try:
                self._input_queue.no_more_input()
            except Exception:
                pass
            self._consumer_thread.join()
            self._consumer_thread = None
            self._handler.uninstall()
            self._handler = None
            self._input_queue = None
            for ctx, old_process in self._old_process.items():
                ctx.Process = old_process

    def __enter__(self) -> "Logregator":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return self.stop()


class Logtor(Logregator):
    """
    A convenience class for initializing a Logregator which emits to either the console, a file or both.

    Parameters
    ----------
    filename : str or Path, optional
        Name of an optional file to write to.

    mode : str, default 'a'
        File writing mode.

    level: str or int, default INFO
        Logging level for the log.

    console : bool, optional
        Whether to emit to the console.
        If not provided, will emit to the console only if a filename is not provided.
        Cannot be False if a filename is not provided.

    name : str, default "LOGTOR"
        Name of the logger.
    """
    def __init__(self, filename: str | Path | None = None, mode: str = 'a', level: LogLevel = logging.INFO,
                 console: bool | None = None, name: str = "LOGTOR"):
        if console is None:
            console = filename is None
        if filename is None:
            if not console:
                raise ValueError("must provide a `filename` when `console` is False")
            logger = get_console_logger(name, level)
        elif console:
            logger = get_file_and_console_logger(name, filename, mode, level)
        else:
            logger = get_file_logger(name, filename, mode, level)
        super().__init__(logger)
