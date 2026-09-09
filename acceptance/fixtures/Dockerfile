FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pymupdf==1.26.3 python-docx==1.2.0 python-pptx==1.0.2 pillow==11.3.0

WORKDIR /generator
COPY generate.py /generator/generate.py
ENTRYPOINT ["python", "/generator/generate.py", "/fixtures"]
