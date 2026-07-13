FROM python:3.11-slim

RUN groupadd --gid 10001 model \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin model
WORKDIR /app
COPY server.py /app/server.py
USER 10001:10001
EXPOSE 8082
ENTRYPOINT ["python", "/app/server.py"]
