#!/bin/bash
# 不用 set -e：某个 N 下 Recall@5 太低时 eval.runner 会返回非零码，但仍要跑完整个 sweep。

# candidateLimit（RRF 两路各自召回条数 N）调优实验：对同一份 eval-set-v2 用不同 N 跑真实
# 混合检索（真实 SiliconFlow embedding + rerank），比较 Recall@k/MRR 与检索延迟的取舍。
# 复用已有评测索引 rag_chunks_eval_v3（语料不随 N 变化，跳过重复入库省时间与调用成本）。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

export JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home
export PATH="${JAVA_HOME}/bin:${PATH}"

set -a
source .env
set +a

DATE_TAG="20260715"
LIMITS=(10 20 30 50)

for N in "${LIMITS[@]}"; do
    echo "════════════════════════════════════════"
    echo "candidateLimit=${N}"
    echo "════════════════════════════════════════"
    OUT="eval/predictions/predicted-v2-candlimit${N}-${DATE_TAG}.jsonl"
    env -u http_proxy -u https_proxy -u all_proxy \
        java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" EvalRetrievalRunner \
        eval/datasets/corpus-index.jsonl eval/datasets/eval-set-v2.jsonl "${OUT}" "${N}" true

    python3 -m eval.runner \
        --ground-truth eval/datasets/eval-set-v2.jsonl \
        --predicted "${OUT}" \
        --output-md "eval/reports/candlimit${N}-${DATE_TAG}.md" \
        --output-json "eval/reports/candlimit${N}-${DATE_TAG}.json" \
        --meta candidateLimit="${N}" \
        --meta embedding=siliconflow/BAAI-bge-m3@1024d \
        --meta rerank=siliconflow/BAAI-bge-reranker-v2-m3 \
        --meta retriever=hybrid-bm25+kNN+rrf+rerank@v1-rerank-gate0.06 || true
done

echo "全部完成"
