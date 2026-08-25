FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120 \
    TZ=Asia/Shanghai

RUN sed -i \
        -e "s|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g" \
        -e "s|https://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --retries 5 -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY seed_phase2.sql ./seed_phase2.sql

RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
