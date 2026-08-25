# Production image for cloud deployment (Render, HuggingFace, Koyeb, Railway).
#
# Two things this file gets wrong easily, both of which it got wrong before:
#
#  1. It starts main.py on 0.0.0.0. main.py now REFUSES to start on a
#     non-loopback interface unless PROJECT2_ACCESS_KEY is set, because the API
#     serves every recording under Data/, accepts uploads, and accepts writes to
#     the extubation audit trail. Set the key in your platform's environment
#     (render.yaml generates one). Do not add --allow-public-no-key here.
#  2. `COPY . .` with no .dockerignore shipped the git history, two 54 MB tunnel
#     binaries, four screen recordings and the entire research corpus - roughly
#     250 MB of payload in a public image. See .dockerignore.
# Build deps live in a throwaway stage so the runtime image does not carry a
# compiler. scikit-learn and scipy publish manylinux wheels, so this is usually
# unused - but it keeps a source build from failing the whole deploy.
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime

# Do not run as root. A container that accepts file uploads should not be able
# to write outside the paths it needs.
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

EXPOSE 8081

# --allow-public-no-key is deliberately NOT here, and must not be added: it is
# the switch that lets main.py serve 0.0.0.0 with no authentication, and this
# CMD carried it while the comment at the top of this file said not to. Every
# image built from that Dockerfile published the recordings, the upload endpoint
# and the audit-trail write endpoint to anyone who could reach the port. If the
# container refuses to start, that is the check working - set
# PROJECT2_ACCESS_KEY in the platform environment.
#
# ${PORT:-8081} matches the ENV default and EXPOSE above; it read 8080 here.
CMD ["sh", "-c", "python -u main.py --host 0.0.0.0 --port ${PORT:-8081} --no-browser"]

