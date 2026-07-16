from __future__ import annotations

import os
import threading

import torch
import torch.nn.functional as F
from transformers import BertForSequenceClassification, BertTokenizer

# IDEA-CCNL/Erlangshen-Roberta-110M-NLI 输出的三分类顺序固定为
# [entailment, neutral, contradiction]（模型卡片给出的约定，不可假设为其他顺序）。
_LABELS = ("entailment", "neutral", "contradiction")

_model: BertForSequenceClassification | None = None
_tokenizer: BertTokenizer | None = None
_load_lock = threading.Lock()


def model_name() -> str:
    return os.getenv("NLI_MODEL_NAME", "IDEA-CCNL/Erlangshen-Roberta-110M-NLI")


def ensure_loaded() -> None:
    """启动阶段预加载模型；重复调用是安全的（幂等）。"""
    global _model, _tokenizer
    if _model is not None and _tokenizer is not None:
        return
    with _load_lock:
        if _model is not None and _tokenizer is not None:
            return
        name = model_name()
        _tokenizer = BertTokenizer.from_pretrained(name)
        _model = BertForSequenceClassification.from_pretrained(name)
        _model.eval()


def is_loaded() -> bool:
    return _model is not None and _tokenizer is not None


def predict(premise: str, hypothesis: str) -> dict[str, float | str]:
    """返回 {"label": ..., "entailment_prob": ..., "neutral_prob": ..., "contradiction_prob": ...}。"""
    ensure_loaded()
    assert _model is not None and _tokenizer is not None
    encoded = _tokenizer.encode(premise, hypothesis, return_tensors="pt")
    with torch.no_grad():
        logits = _model(encoded).logits
    probabilities = F.softmax(logits, dim=-1)[0].tolist()
    scores = dict(zip(_LABELS, probabilities))
    label = max(scores, key=scores.get)
    return {
        "label": label,
        "entailment_prob": scores["entailment"],
        "neutral_prob": scores["neutral"],
        "contradiction_prob": scores["contradiction"],
    }
