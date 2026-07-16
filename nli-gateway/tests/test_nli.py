"""针对 app/main.py 的 /nli /health 端点回归测试。

模型加载/推理耗资源且需要网络下载权重，单测里用 monkeypatch 替身
app.model.predict/is_loaded，只验证 FastAPI 路由/校验逻辑本身，
不依赖真实模型权重——真实模型效果由 eval/scripts/analyze_nli_threshold.py
的真实回归验证覆盖。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import model as nli_model
from app.main import app

client = TestClient(app)


class TestHealth:
    def test_reports_up_when_model_loaded(self, monkeypatch):
        monkeypatch.setattr(nli_model, "is_loaded", lambda: True)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "UP"}

    def test_reports_loading_when_model_not_yet_loaded(self, monkeypatch):
        monkeypatch.setattr(nli_model, "is_loaded", lambda: False)
        response = client.get("/health")
        assert response.json() == {"status": "LOADING"}


class TestNli:
    def test_returns_entailment_verdict(self, monkeypatch):
        monkeypatch.setattr(
            nli_model,
            "predict",
            lambda premise, hypothesis: {
                "label": "entailment",
                "entailment_prob": 0.95,
                "neutral_prob": 0.03,
                "contradiction_prob": 0.02,
            },
        )
        response = client.post("/nli", json={"premise": "今天的饭不好吃", "hypothesis": "今天心情不好"})
        assert response.status_code == 200
        body = response.json()
        assert body["label"] == "entailment"
        assert body["entailment_prob"] == 0.95

    def test_missing_premise_returns_422(self):
        response = client.post("/nli", json={"premise": "", "hypothesis": "某个假设"})
        assert response.status_code == 422

    def test_missing_hypothesis_returns_422(self):
        response = client.post("/nli", json={"premise": "某个前提", "hypothesis": ""})
        assert response.status_code == 422

    def test_missing_field_entirely_returns_422(self):
        response = client.post("/nli", json={"premise": "某个前提"})
        assert response.status_code == 422
