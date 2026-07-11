# W2 D14 hand-run env — throwaway; replaced by official harness images in W3.
# pylint 2.15.dev: the repo's own requirements_test_min.txt carries the exact astroid
# pin plus the test deps test_self.py needs (pytest, pytest-timeout, gitpython, ...).
FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/pylint-dev/pylint /workspace \
    && git -C /workspace checkout 3c5eca2ded3dd2b59ebaf23eb289453b5d2930f0
# requirements_test_min.txt line 1 is `-e .[...]` — relative, so pip must run from the repo
RUN cd /workspace && pip install --no-cache-dir -r requirements_test_min.txt \
    && rm -rf /workspace/.git
# resolver gives pytest 7.4 (vendored py.py shim, no py.io) + pytest-benchmark 3.4.1
# (needs real py.io at configure time) -> INTERNALERROR on every run; the real `py`
# package dir takes import precedence over the shim module and restores py.io.
RUN pip install --no-cache-dir "py==1.11.0"
WORKDIR /workspace
