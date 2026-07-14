#!/usr/bin/env python3
"""
基于 corpus-index.jsonl 自动生成 QA 标注集 v2（题目从 snippet 实体抽取）。

改进点 vs v1：
- 题目不再用模板填充，直接从 chunk snippet 抽具体接口/字段/端口
- 拒答题每篇不同（基于文档主题生成）
- 每道题 ground_truth 用真实 chunk_id
"""
import json
import re
from collections import defaultdict
from pathlib import Path

INPUT = Path("eval/datasets/corpus-index.jsonl")
OUTPUT = Path("eval/datasets/eval-set-2026Q3.jsonl")
KB_ID = "kb-bdzdc"
ORG_ID = "org-bdzdc"


def extract_apis(text):
    return list(dict.fromkeys(re.findall(r"/[A-Za-z][A-Za-z0-9_\-/{}\$]+", text)))[:3]


def extract_classes(text):
    return list(dict.fromkeys(re.findall(r"\b[A-Z][A-Za-z0-9]+(?:Service|Controller|Mapper|Repository|Util)\b", text)))[:3]


def extract_fields(text):
    return list(dict.fromkeys(re.findall(r"\b(?:pcxx|msxx|smi|img|sydj|qksm)_\w+\b", text)))[:3]


def extract_ports(text):
    return list(dict.fromkeys(re.findall(r":(\d{4,5})\b", text)))[:3]


def first_sentence(text, n=200):
    text = text.strip().replace("\n", " ")
    # 截到第一个句号/问号/换行
    m = re.search(r"[。；;！!？?\n]", text)
    return text[: m.start() if m else n].strip()


def make_specific_question(chunk, doc_name):
    """从 chunk 实体出题，不再用模板。"""
    snippet = chunk.get("snippet", "")
    full = chunk.get("content", "")
    text = (snippet or full)[:600]
    hp = " / ".join(str(x) for x in chunk.get("heading_path", []) if x) or doc_name

    # 接口路径题
    apis = extract_apis(text)
    if apis and any(k in hp for k in ("接口", "API", "共享", "上传", "查询")):
        return f"在 [{hp}] 中，接口路径 {apis[0]} 的请求/响应是什么？", "api"
    # 类名题
    classes = extract_classes(text)
    if classes:
        return f"在 [{hp}] 中提到的 {classes[0]} 类，职责是什么？", "class-name"
    # 字段题
    fields = extract_fields(text)
    if fields:
        return f"[{hp}] 这一节中提到的 {fields[0]} 字段含义是什么？", "data-structure"
    # 端口题
    ports = extract_ports(text)
    if ports:
        return f"[{hp}] 中提到的端口 {ports[0]} 是哪个服务的？", "config"
    # 兜底
    sent = first_sentence(text)
    if sent:
        return f"[{hp}] 这一节的核心内容是什么？请用一句话总结。", "module"
    return f"[{hp}] 这一节讲了什么？", "module"


def refusal_question_for_doc(doc_name):
    """每篇文档主题不同，拒答题要多样化。"""
    base = doc_name.replace(".md", "").replace(".pdf", "").replace(".docx", "")
    pool = [
        f"这份文档里有没有详细说明 [{base}] 与 'Spring Cloud Eureka' 的兼容版本？",
        f"[{base}] 里是否给出了基于 OAuth2 的第三方登录对接方案？",
        f"[{base}] 中是否有关于 K8s 上部署的 Helm Chart 示例？",
        f"请说明 [{base}] 文档里没提到的、但生产必需的灾备方案",
        f"对比 [{base}] 和 Kubernetes 监控体系 Prometheus 的指标对接方式",
        f"[{base}] 里是否提到过 IPv6 网络下的特殊处理",
        f"[{base}] 中有没有关于 GPU 加速解析的方案",
        f"说明 [{base}] 文档中涉及的 PII 数据脱敏策略",
        f"[{base}] 是否包含性能压测数据（QPS/P99）",
        f"[{base}] 里如何处理跨租户的数据权限隔离",
    ]
    # 简单按 hash 选一个（保证可复现）
    return pool[hash(doc_name) % len(pool)]


def difficulty_for(chunk):
    snip = chunk.get("snippet", "")
    if len(snip) > 150 or "{" in snip or "HTTP" in snip:
        return "hard"
    if len(snip) > 80:
        return "medium"
    return "easy"


def category_for_doc(doc_name):
    if "数据统计接口" in doc_name or "共享交换" in doc_name or "查询测量标志点" in doc_name or "上传测量标志点" in doc_name:
        return "api"
    if "源代码" in doc_name:
        return "class-name"
    if "导出" in doc_name:
        return "data-structure"
    if "启动" in doc_name:
        return "config"
    if "复测" in doc_name or "漏洞" in doc_name:
        return "troubleshoot"
    return "module"


def main():
    chunks = []
    with INPUT.open(encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))

    by_doc = defaultdict(list)
    for c in chunks:
        by_doc[c["document_name"]].append(c)

    qa = []
    counter = 1

    for doc in sorted(by_doc.keys()):
        cs = by_doc[doc]
        if not cs:
            continue
        cat = category_for_doc(doc)

        # 选 5 道可标题：1 主题 + 2 细节 + 1 接口/类 + 1 字段/端口（按 snippet 特征）
        # 主题 = 最长 chunk
        theme = max(cs, key=lambda c: len(c.get("content", "")))
        # 细节 = heading 层级 ≥ 2、长度 > 80、均匀挑 2
        detail_pool = [c for c in cs if c is not theme and len(c.get("content", "")) > 80]
        step = max(1, len(detail_pool) // 7)
        details = [detail_pool[i] for i in range(0, len(detail_pool), step)][:7]
        # 接口/字段题 = 找有 apis 或 fields 的 chunk
        special = None
        for c in cs:
            text = (c.get("content", "") or "")[:600]
            if extract_apis(text) or extract_classes(text) or extract_fields(text):
                special = c
                break
        if not special:
            special = theme

        picks = [theme] + details + [special]
        # 去重
        seen = set()
        uniq_picks = []
        for c in picks:
            if c["chunk_id"] not in seen:
                seen.add(c["chunk_id"])
                uniq_picks.append(c)
        picks = uniq_picks

        for c in picks:
            q_text, q_cat = make_specific_question(c, doc)
            qa.append({
                "id": f"q-{counter:03d}",
                "question": q_text,
                "ground_truth_chunk_ids": [c["chunk_id"]],
                "expect_refusal": False,
                "category": q_cat or cat,
                "difficulty": difficulty_for(c),
                "kb_id": KB_ID,
                "org_id": ORG_ID,
            })
            counter += 1

        # 1 道拒答题
        qa.append({
            "id": f"q-{counter:03d}",
            "question": refusal_question_for_doc(doc),
            "ground_truth_chunk_ids": [],
            "expect_refusal": True,
            "refusal_reason": "OUT_OF_SCOPE",
            "category": "out-of-scope",
            "difficulty": "hard",
            "kb_id": KB_ID,
            "org_id": ORG_ID,
        })
        counter += 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        for q in qa:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # 统计
    by_cat = defaultdict(int)
    for q in qa:
        by_cat[q["category"]] += 1
    print(f"✅ 生成 {len(qa)} 道题 → {OUTPUT}")
    print("\n按 category:")
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {k:>20}: {v}")
    by_doc_q = defaultdict(int)
    for q in qa:
        if q["ground_truth_chunk_ids"]:
            for c in chunks:
                if c["chunk_id"] == q["ground_truth_chunk_ids"][0]:
                    by_doc_q[c["document_name"]] += 1
                    break
        else:
            by_doc_q["(拒答题)"] += 1
    print("\n按文档:")
    for k, v in sorted(by_doc_q.items(), key=lambda x: -x[1]):
        print(f"  {k[:55]:>55}: {v}")


if __name__ == "__main__":
    main()
