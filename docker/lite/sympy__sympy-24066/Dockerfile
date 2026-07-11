# W2 D14 hand-run env — throwaway; replaced by official harness images in W3.
# sympy 1.12.dev: pure python, mpmath is the only runtime dep.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/sympy/sympy /workspace \
    && git -C /workspace checkout 514579c655bf22e2af14f0743376ae1d7befe345
RUN pip install --no-cache-dir "mpmath==1.3.0" "pytest==7.4.4" \
    && pip install --no-cache-dir --no-deps -e /workspace \
    && rm -rf /workspace/.git
WORKDIR /workspace
