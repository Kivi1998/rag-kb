FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    XDG_CACHE_HOME=/models \
    NLTK_DATA=/models/nltk_data

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# deepdoc 的 rag_tokenizer 依赖这几个 nltk 语料/分词模型
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('wordnet'); nltk.download('omw-1.4')"
COPY app ./app

RUN useradd --system --uid 10001 parser \
    && mkdir -p /models/huggingface \
    && chown -R parser:parser /app /models
USER parser

EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8081/ready || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--limit-concurrency", "8"]
