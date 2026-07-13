FROM python:3.11-slim

RUN pip install --no-cache-dir requests==2.32.4 "psycopg[binary]==3.2.9" minio==7.2.16
RUN groupadd --gid 10001 acceptance \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin acceptance \
    && mkdir -p /reports \
    && chown 10001:10001 /reports

WORKDIR /acceptance
COPY run_acceptance.py /acceptance/run_acceptance.py
USER 10001:10001
ENTRYPOINT ["python", "/acceptance/run_acceptance.py"]
