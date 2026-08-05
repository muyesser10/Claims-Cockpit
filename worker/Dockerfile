# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app

# torch first, and from PyTorch's CPU-only index. PyPI's default Linux wheel
# ships the CUDA kernels inside the wheel itself: 502 MB against 183 MB for the
# +cpu build, on a service with no GPU. (Measured 2026-08-05, torch 2.13.0,
# manylinux/cp311. Older torch releases also dragged in separate nvidia-*
# wheels; 2.13 no longer does, the weight is in the wheel.) The install below
# then finds torch already satisfied and skips it.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt requirements-worker.txt ./
# The cache mount is what stops a changed requirements line from re-downloading
# every wheel: BuildKit keeps pip's cache outside the image, so the layer is
# rebuilt but the packages come off disk. Do not add --no-cache-dir here - it
# tells pip to ignore exactly that cache.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -r requirements-worker.txt

COPY . .
CMD ["python", "-m", "worker.main"]
