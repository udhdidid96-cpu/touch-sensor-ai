FROM python:3.13-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim AS runtime

RUN useradd --create-home --uid 10001 project2
WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=project2:project2 main.py ./
COPY --chown=project2:project2 web/ ./web/
COPY --chown=project2:project2 Data/ ./Data/
COPY --chown=project2:project2 requirements.txt ./

RUN mkdir -p /app/Data/Custom_Uploads && chown -R project2:project2 /app/Data

USER project2

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8081

RUN python -u main.py --no-serve

EXPOSE 8081

CMD ["sh", "-c", "python -u main.py --host 0.0.0.0 --port ${PORT:-8081} --no-browser"]

