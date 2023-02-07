import pytest
import logging
import logging.handlers
import multiprocessing as mp
from contextlib import contextmanager

from epic.logging import (
    get_logger,
    get_console_logger,
    get_file_logger,
    get_file_and_console_logger,
    class_logger,
    ClassLogger,
    Logregator,
    Logtor,
)


# explicit string (not calculated automatically), for testing
MODULE_NAME = 'epic.logging.tests.test_logger'

try:
    module_logger = get_logger()
except Exception:
    module_logger = None


class TestGetLogger:
    def test_returned_logger(self):
        assert isinstance(get_logger(), logging.Logger)

    def test_named(self):
        name = "testname"
        assert get_logger(name).name == name

    def test_unnamed_in_function(self):
        assert get_logger().name == f'{MODULE_NAME}.test_unnamed_in_function'

    def test_unnamed_in_module(self):
        assert getattr(module_logger, 'name', None) == MODULE_NAME

    def test_log_level(self):
        for level_name in ('INFO', 'DEBUG', 'ERROR', 'CRITICAL', 'WARNING', 'NOTSET'):
            level_num = logging.getLevelName(level_name)
            assert get_logger(level=level_name).level == level_num
            assert get_logger(level=level_num).level == level_num

    def test_no_handlers(self):
        assert get_logger().hasHandlers()

    def test_handlers(self):
        name = 'test_handlers_logger'
        handlers = [logging.StreamHandler(), logging.handlers.SysLogHandler()]
        assert get_logger(name, 'INFO', *handlers).handlers == handlers
        # get the same logger again; test if old handlers are removed before setting new ones
        h = logging.handlers.MemoryHandler(0)
        assert get_logger(name, 'INFO', h).handlers == [h]


class TestClassLogger:
    cls_logger = ClassLogger()

    PARENT_NAME = 'parent_logger'
    child_cls_logger = ClassLogger(get_logger(PARENT_NAME))

    def test_unnamed_class_logger(self):
        assert self.cls_logger.name == f'{MODULE_NAME}.TestClassLogger'

    def test_child_class_logger(self):
        assert self.child_cls_logger.name == f'{self.PARENT_NAME}.TestClassLogger'

    def test_default_instance(self):
        assert isinstance(class_logger, ClassLogger)


class TestPreconfiguredLoggers:
    @staticmethod
    def _examine_logger(logger, name, level, *handler_classes):
        assert isinstance(logger, logging.Logger)
        assert logger.name == name
        assert logger.level == level
        assert len(logger.handlers) == len(handler_classes)
        assert all(isinstance(h, handler_classes) for h in logger.handlers)

    def test_console_logger(self):
        name = 'console_logger'
        level = logging.INFO
        self._examine_logger(get_console_logger(name, level), name, level, logging.StreamHandler)

    def test_file_logger(self, tmp_path):
        name = 'file_logger'
        path = tmp_path / 'temp.txt'
        level = logging.DEBUG
        for p in (path, str(path)):
            self._examine_logger(get_file_logger(name, p, level=level), name, level, logging.FileHandler)

    def test_file_and_console_logger(self, tmp_path):
        name = 'file_and_console_logger'
        path = tmp_path / 'temp.txt'
        level = logging.WARNING
        for p in (path, str(path)):
            self._examine_logger(
                get_file_and_console_logger(name, p, level=level), name, level,
                logging.StreamHandler, logging.FileHandler,
            )

    def test_encoding(self, tmp_path):
        logger = get_console_logger('test_encoding_emoji_console')
        logger.info("⚠️")
        logger = get_file_logger('test_encoding_emoji_file', tmp_path / 'emoji.log')
        logger.info("⚠️")
        logger = get_file_and_console_logger('test_encoding_emoji_file_and_console', tmp_path / 'emoji_fac.log')
        logger.info("⚠️")


def business_code(logname: str, message, level=logging.INFO) -> None:
    """Some code that uses logging to be run by child processes and such in order to test Logregator."""
    logger = logging.getLogger(logname)
    logger.setLevel(level)
    logger.log(level, message)


class ListHandler(logging.Handler):
    """A handler that emits log records to a list it is given."""
    def __init__(self, output_list: list[str], level):
        super().__init__(level=level)
        self.output_list = output_list

    def emit(self, record: logging.LogRecord) -> None:
        self.output_list.append(self.format(record))


class TestLogregator:
    @staticmethod
    @contextmanager
    def sink_logger(name: str, output_list: list[str], level=logging.INFO, msg_format: str = "%(name)s %(message)s"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if isinstance(handler, ListHandler) and handler.output_list is output_list:
                handler.setLevel(level)
                break
        else:
            handler = ListHandler(output_list, level)
            logger.addHandler(handler)
        handler.setFormatter(logging.Formatter(msg_format))
        logger.setLevel(level)
        try:
            yield logger
        finally:
            logger.removeHandler(handler)

    @pytest.mark.parametrize("msg", ("local test", 123))
    def test_local(self, msg):
        sink_name = 'test_local'
        name = "internal"
        messages = []
        with self.sink_logger(sink_name, messages) as sink, Logregator(sink):
            business_code(name, msg)
        assert len(messages) == 1
        assert messages[0] == f"{name} [{sink_name}] - {msg}"

    def test_multiprocessing(self, n=2):
        sink_name = 'test_multiprocessing'
        names_msgs = [(f"internal{i}", f"mp test #{i}") for i in range(n)]
        messages = []
        with self.sink_logger(sink_name, messages) as sink, Logregator(sink):
            processes = [mp.Process(target=business_code, args=x) for x in names_msgs]
            for p in processes:
                p.start()
            for p in processes:
                p.join()
        assert len(messages) == n
        assert set(messages) == {
            f"{name} [{sink_name} PID {p.pid}] - {msg}" for p, (name, msg) in zip(processes, names_msgs)
        }

    def test_local_nested(self):
        outer_sink_name = 'test_local_nested_outer'
        inner_sink_name = 'test_local_nested_inner'
        outer_messages = []
        inner_messages = []
        names_msgs = [(f"internal{i}", f"nested test #{i}") for i in range(3)]
        with self.sink_logger(outer_sink_name, outer_messages) as outer_sink, Logregator(outer_sink):
            business_code(*names_msgs[0])
            with self.sink_logger(inner_sink_name, inner_messages) as inner_sink, Logregator(inner_sink):
                business_code(*names_msgs[1])
            business_code(*names_msgs[2])
        assert len(inner_messages) == 1
        assert inner_messages[0] == "%s [%%s] - %s" % names_msgs[1] % inner_sink_name
        assert outer_messages == [f"{name} [{outer_sink_name}] - {msg}" for name, msg in names_msgs]

    def test_multiprocessing_nested(self):
        outer_sink_name = 'test_multiprocessing_nested_outer'
        inner_sink_name = 'test_multiprocessing_nested_inner'
        outer_messages = []
        inner_messages = []
        names_msgs = [(f"internal{i}", f"mp nested test #{i}") for i in range(3)]
        processes = []
        with self.sink_logger(outer_sink_name, outer_messages) as outer_sink, Logregator(outer_sink):
            p1 = mp.Process(target=business_code, args=names_msgs[0])
            processes.append(p1)
            p1.start()
            with self.sink_logger(inner_sink_name, inner_messages) as inner_sink, Logregator(inner_sink):
                p2 = mp.Process(target=business_code, args=names_msgs[1])
                processes.append(p2)
                p2.start()
                p2.join()
            p3 = mp.Process(target=business_code, args=names_msgs[2])
            processes.append(p3)
            p3.start()
            p1.join()
            p3.join()
        assert len(inner_messages) == 1
        assert inner_messages[0] == "%s [%%s PID %%d] - %s" % names_msgs[1] % (inner_sink_name, processes[1].pid)
        assert len(outer_messages) == len(names_msgs)
        assert set(outer_messages) == {
            f"{name} [{outer_sink_name} PID {p.pid}] - {msg}" for p, (name, msg) in zip(processes, names_msgs)
        }

    def test_sink_log_level(self):
        sink_name = 'test_sink_log_level'
        name = "internal"
        msg = "test level %d"
        messages = []
        with self.sink_logger(sink_name, messages, level=logging.INFO) as sink, Logregator(sink):
            business_code(name, msg % logging.DEBUG, level=logging.DEBUG)
        assert len(messages) == 0
        with self.sink_logger(sink_name, messages, level=logging.DEBUG) as sink, Logregator(sink):
            business_code(name, msg % logging.INFO, level=logging.INFO)
        assert len(messages) == 1
        assert messages[0] == f"{name} [{sink_name}] - {msg % logging.INFO}"


class TestLogtor:
    def test_logregator_subclass(self):
        assert issubclass(Logtor, Logregator)

    def test_filename_provided(self, tmp_path):
        path = tmp_path / 'temp.txt'
        for console in (True, False):
            assert any(
                isinstance(h, logging.FileHandler) for h in Logtor(filename=path, console=console).logger.handlers
            )
        assert any(isinstance(h, logging.FileHandler) for h in Logtor(filename=path).logger.handlers)

    def test_no_filename(self):
        with pytest.raises(ValueError):
            Logtor(console=False)
        assert any(isinstance(h, logging.StreamHandler) for h in Logtor().logger.handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in Logtor(console=True).logger.handlers)
