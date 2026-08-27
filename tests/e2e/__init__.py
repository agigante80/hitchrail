"""A package on purpose.

Without `__init__.py` pytest inserts this directory on `sys.path`, and the
bare `from conftest import ...` that every other test module uses then
resolves to THIS directory's conftest instead of `tests/conftest.py`. The
symptom is an ImportError in four unrelated files.

As a package, the e2e conftest is reached as `tests.e2e.conftest` and shadows
nothing.
"""
