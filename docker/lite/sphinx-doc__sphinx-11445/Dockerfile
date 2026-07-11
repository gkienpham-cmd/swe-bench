# W2 D14 hand-run env — throwaway; replaced by official harness images in W3.
# sphinx 7.1 (Jul 2023): deps carry sane pins (docutils<0.21 etc.), so pip resolves;
# [test] extra skipped to avoid cython/gcc on slim — F2P (test_util_rst) needs pytest only.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/sphinx-doc/sphinx /workspace \
    && git -C /workspace checkout 71db08c05197545944949d5aa76cd340e7143627
RUN pip install --no-cache-dir -e /workspace "pytest==7.4.4" "html5lib==1.1" \
    && rm -rf /workspace/.git
WORKDIR /workspace
