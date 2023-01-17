# Epic logging - Easy logging with multiprocessing support
[![Epic-logging CI](https://github.com/Cybereason/epic-logging/actions/workflows/ci.yml/badge.svg)](https://github.com/Cybereason/epic-logging/actions/workflows/ci.yml)


## What is it?

The **epic-logging** Python library makes logging super easy. It is built on top of the builtin `logging` 
framework, and provides two main functionalities:
* Easily create loggers that are named appropriately for their scope (function, class or module).
* Capture log records emitted from within a context, including from child processes, and redirect them
to a designated sink logger.

## Paradigm
It is important to separate any dependency between the emission and collection of log records.
The emitter should not be concerned with the formatting of the records, where they are going and who
will collect them, only with the log level. On the other hand, the collecting end should not be concerned with
where within the code the log records came from. It should **know** where they came from, but should still
collect them, even if they were emitted from child processes, subpackages, etc.

## Usage

### Get a logger for your module, function or class

To get a logger for a module, use `get_logger` in the module level:
```python
from epic.logging import get_logger

logger = get_logger()
```
The logger name is automatically set to be the fully qualified module name.

To get a logger for a function, use `get_logger` inside the function:
```python
from epic.logging import get_logger

def func():
    logger = get_logger()
```
The logger name is automatically set to be the fully qualified function name.

To get a logger for a class, use the `ClassLogger` to create a class member:
```python
from epic.logging import ClassLogger

class MyClass:
    logger = ClassLogger()
```
Alternatively, use the ready-made `class_logger` instance:
```python
from epic.logging import class_logger

class MyClass:
    logger = class_logger
```
The class logger name is automatically set to be the full class name.

### Convenience pre-configured loggers
The `epic.logging` package provides some convenient functions for getting pre-configured loggers for quick use.
These are meant to be used primarily when working interactively.

#### Console logger
To get a logger that emits to the console, use `get_console_logger`:
```python
from epic.logging import get_console_logger

logger = get_console_logger('LOGNAME')
```

#### File logger
To get a logger that emits to a file, use `get_file_logger`:
```python
from epic.logging import get_file_logger

logger = get_file_logger('LOGNAME', 'filename.log')
```

#### Both console and file
To get a logger that emits to both the console and a file, use `get_file_and_console_logger`:
```python
from epic.logging import get_file_and_console_logger

logger = get_file_and_console_logger('LOGNAME', 'filename.log')
```

### The Logregator &mdash; A logging aggregator
A `Logregator` is used for the aggregation of log records. It is initialized with a logger object
which acts as a sink&mdash;within the context of the `Logregator` block, all log records emitted above the sink's
log level are redirected to the sink logger. Crucially, **this also works for log records emitted by sub-processes**.
This makes `Logregator` the preferred way to collect log records, whether working interactively or in a
script. As the consumer, you don't care if functions or packages use multiprocessing internally or not,
you just want to get their log records. This is exactly what `Logregator` does.

Using `Logregator` is very simple. It is initialized with a sink logger, and used as a context manager:
```python
from epic.logging import Logregator, get_console_logger

with Logregator(get_console_logger('LOGNAME')):
    ...
    # All logs here, even from sub-processes, are printed to the console.
```

#### Convenience `Logregator` initializer
For the extremely common use cases of initializing a `Logregator` over a logger which emits to the console
and/or a file, it is convenient to use `Logtor`, a subclass of `Logregator`:
```python
from epic.logging import Logtor

# Emit to the console
with Logtor():
    ...

# Emit to a file
with Logtor('filename.log'):
    ...

# Emit to both the console and a file
with Logtor('filename.log', console=True):
    ...
```
