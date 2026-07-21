"""`SelfCheckResult` 测试。

对照 Java 版 `ragcore/generation/SelfCheckResult.java` record:验证不可变语义、归一化、
`has_unsupported_claims` / `none()` / `build_warning_message()` 行为。warning 文案本身
按设计原样保留(翻译/改写不在移植范围),测试只验证拼接结构(总述行 + 每条 claim 一行
`- ` 前缀)。
"""

from __future__ import annotations

from app.ragcore.generation.self_check_result import SelfCheckResult


class TestNoneFactory:
    def test_none_has_empty_claims(self):
        result = SelfCheckResult.none()
        assert result.unsupported_claims == ()

    def test_none_has_no_unsupported_claims(self):
        result = SelfCheckResult.none()
        assert result.has_unsupported_claims is False


class TestNormalization:
    def test_none_claims_normalized_to_tuple(self):
        result = SelfCheckResult(unsupported_claims=[])
        assert result.unsupported_claims == ()

    def test_list_normalized_to_tuple(self):
        result = SelfCheckResult(unsupported_claims=["a", "b"])
        assert result.unsupported_claims == ("a", "b")
        assert isinstance(result.unsupported_claims, tuple)

    def test_existing_tuple_preserved(self):
        result = SelfCheckResult(unsupported_claims=("a", "b"))
        assert result.unsupported_claims == ("a", "b")


class TestHasUnsupportedClaims:
    def test_empty_is_false(self):
        assert SelfCheckResult.none().has_unsupported_claims is False

    def test_with_claims_is_true(self):
        result = SelfCheckResult(unsupported_claims=["claim1"])
        assert result.has_unsupported_claims is True


class TestImmutability:
    def test_result_is_frozen(self):
        result = SelfCheckResult(unsupported_claims=["x"])
        try:
            result.unsupported_claims = ("y",)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            assert "frozen" in str(exc).lower() or "cannot" in str(exc).lower() or "FrozenInstanceError" in type(exc).__name__
        else:
            raise AssertionError("SelfCheckResult 应当不可变")


class TestBuildWarningMessage:
    def test_empty_claims_still_produces_header_only_message(self):
        """`build_warning_message` 是给 has_unsupported_claims=True 用的,空 claims 时
        调用方本不该调,但行为上仍能给出仅有总述行的输出——这条是契约,不是建议用法。"""
        message = SelfCheckResult.none().build_warning_message()
        assert message.startswith("⚠️ 自检提示:以下内容未在参考资料中找到明确支撑")

    def test_single_claim_appended_with_bullet(self):
        result = SelfCheckResult(unsupported_claims=["A 句子（未标注引用来源）"])
        message = result.build_warning_message()
        assert message.startswith("⚠️ 自检提示:")
        assert "\n- A 句子（未标注引用来源）" in message

    def test_multiple_claims_each_on_own_line(self):
        result = SelfCheckResult(
            unsupported_claims=[
                "claim1（未标注引用来源）",
                "claim2（标注了引用，但相关性较低）",
            ]
        )
        message = result.build_warning_message()
        assert "\n- claim1（未标注引用来源）" in message
        assert "\n- claim2（标注了引用，但相关性较低）" in message
        # 两条 claim 必须各占一行,避免 warning 文案糊成一坨
        assert message.count("\n- ") == 2
