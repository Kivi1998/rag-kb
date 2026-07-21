"""NliVerdict / NliClient 协议基础测试。

对照 Java 版 `NliVerdict.java`(record) + `NliClient.java`(interface)。
"""

from __future__ import annotations

from app.ragcore.nli.client import NliClient, NliVerdict


class _FakeNliClient:
    async def check(self, premise: str, hypothesis: str) -> NliVerdict:
        return NliVerdict(label="entailment", entailment_prob=1.0, neutral_prob=0.0, contradiction_prob=0.0)


class TestNliVerdict:
    def test_is_immutable_value_object(self):
        verdict = NliVerdict(label="neutral", entailment_prob=0.3, neutral_prob=0.5, contradiction_prob=0.2)
        assert verdict.label == "neutral"
        assert verdict.entailment_prob == 0.3
        assert verdict.neutral_prob == 0.5
        assert verdict.contradiction_prob == 0.2

    def test_equality_is_value_based(self):
        v1 = NliVerdict(label="entailment", entailment_prob=0.9, neutral_prob=0.05, contradiction_prob=0.05)
        v2 = NliVerdict(label="entailment", entailment_prob=0.9, neutral_prob=0.05, contradiction_prob=0.05)
        assert v1 == v2


class TestNliClientProtocol:
    def test_structurally_compatible_class_is_recognized(self):
        assert isinstance(_FakeNliClient(), NliClient)

    def test_unrelated_class_is_not_recognized(self):
        class _Empty:
            pass

        assert not isinstance(_Empty(), NliClient)
