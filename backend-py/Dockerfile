# backend-py 生产/验收共用镜像。
#
# 取代已退役的 Java 版 backend/Dockerfile + Dockerfile.acceptance:Java 当年拆成两个文件
# 是因为 Docker Desktop 内容缓存偶发损坏、解析不出 JRE manifest,只能绕开容器内编译改成
# 宿主机先 `mvn package` 再 COPY 现成 JAR。Python 没有这个问题(pip 安装的是解释器可直接
# 加载的包,不存在"编译产物损坏导致 JRE 起不来"这类问题),两边(本地部署 / acceptance
# 验收)共用这一份 Dockerfile 即可,不需要 Dockerfile.acceptance 变体。
#
# 两阶段构建:
#   builder — 装 pyproject.toml 里的全部依赖(含 onnxruntime/opencv-python-headless 等
#             deepdoc OCR 重依赖,以及 datrie/pyclipper 这类需要本地编译 C 扩展的包),
#             产物是一个自包含的 venv。
#   runtime — 精简 python:3.13-slim 基础镜像,只 COPY 训练好的 venv + 应用代码,不含
#             编译工具链,体积和攻击面都更小。
#
# Layer 缓存策略:先单独 COPY pyproject.toml 装依赖,再 COPY app/ 源码——只改业务代码时
# 前面的依赖安装层完全命中缓存,不会每次改代码都重装 onnxruntime 这类大依赖。

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# build-essential/gcc/g++: datrie、pyclipper 等包在部分平台(如 arm64)没有随
# pip 安装可直接使用的预编译 wheel,需要本地编译 C 扩展。运行期最终镜像不需要
# 这套工具链,靠多阶段构建隔离在 builder 层,不进最终镜像。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

# 只拷贝依赖清单这一层,充分利用 Docker layer 缓存:后面改 app/ 源码不会使这层失效,
# 不用每次改代码都重装一遍 onnxruntime/opencv-python-headless 这些体积大、耗时长的依赖。
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# 运行期系统依赖:
#   - libgomp1:  onnxruntime 运行时链接 OpenMP。
#   - curl:      compose healthcheck 用(`curl -fsS http://127.0.0.1:8090/health`)。
#   - ca-certificates: 出站 HTTPS(embedding/ES/HuggingFace 模型下载等)校验证书链需要。
# opencv-python-headless 本身就是免 GUI 依赖(libGL 等)的发行版,不需要额外装图形库。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 非 root 用户,uid/gid 对齐已退役 Java 版的约定(10001),最小权限运行。
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/tmp/hf-cache

# 非 root 用户是 --no-create-home,没有 /home/app;镜像/生产环境常以 read_only
# 根文件系统运行(见 acceptance/compose.yml 的 read_only: true + /tmp tmpfs),
# deepdoc(OCR/版面分析/表格结构识别)首次加载模型时走 huggingface_hub 默认缓存
# 路径 ~/.cache/huggingface 会写失败——这个不像 huqie trie 那样能静默降级,
# deepdoc 模型下不下来就是真的不可用。指到 /tmp 下(tmpfs 可写)是必须的,不是
# 可选优化。

WORKDIR /app
COPY app ./app

# deepdoc 的 res/ 目录(huqie.txt 分词词典等)需要在应用用户下可读;huqie 分词器
# 首次实例化时会在同目录尝试写入 huqie.txt.trie 缓存(见 rag_tokenizer.py 的
# loadDict_),写入失败会被其自身 try/except 吞掉、退化为每次进程内重建、不影响
# 功能——所以这里 chown 是"尽量让缓存可写"的优化,不是功能强依赖。
RUN chown -R app:app /app

USER app

EXPOSE 8090

# 必须绑 0.0.0.0 而不是 127.0.0.1,否则同一 compose 网络里的其他容器(worker-a/
# worker-b 复用同一镜像、Docker healthcheck 探测)都连不进来。
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
