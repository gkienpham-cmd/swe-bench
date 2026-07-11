# W2 D14 hand-run env — throwaway; replaced by official harness images in W3.
# flask 2.0 (May 2021): unbounded setup.py deps resolve to werkzeug 3.x today and
# break the 2.0 test suite, so the era stack is pinned explicitly.
# .git is removed after install: the container's .git arrives solely via the sandbox
# docker cp from the host checkout, so git_diff() is guaranteed vs base_commit.
FROM python:3.9-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/pallets/flask /workspace \
    && git -C /workspace checkout d8c37f43724cd9fb0870f77877b7c4c7e38a19e0
RUN pip install --no-cache-dir \
        "werkzeug==2.0.3" "jinja2==3.0.3" "markupsafe==2.0.1" "itsdangerous==2.0.1" \
        "click==8.0.4" "blinker==1.4" "asgiref==3.4.1" "python-dotenv==0.19.2" \
        "pytest==6.2.5" \
    && pip install --no-cache-dir --no-deps -e /workspace \
    && rm -rf /workspace/.git
WORKDIR /workspace
