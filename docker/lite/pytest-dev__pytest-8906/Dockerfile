# W2 D14 hand-run env — throwaway; replaced by official harness images in W3.
# pytest 7.0.0.dev at base commit; editable install IS the pytest under test
# (self-hosting: run_tests' `python3 -m pytest` runs the agent-edited code).
# setuptools_scm needs .git at install time — install before the .git removal.
FROM python:3.9-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/pytest-dev/pytest /workspace \
    && git -C /workspace checkout 69356d20cfee9a81972dcbf93d8caf9eabe113e8
RUN pip install --no-cache-dir \
        "attrs==21.4.0" "iniconfig==1.1.1" "packaging==21.3" "pluggy==1.0.0" \
        "py==1.11.0" "tomli==1.2.3" "setuptools-scm==6.4.2" \
        "hypothesis==6.36.0" "xmlschema==1.9.2" \
    && pip install --no-cache-dir --no-deps -e /workspace \
    && rm -rf /workspace/.git
WORKDIR /workspace
