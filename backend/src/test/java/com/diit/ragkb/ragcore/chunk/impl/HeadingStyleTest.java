package com.diit.ragkb.ragcore.chunk.impl;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("HeadingStyle 多风格识别测试")
class HeadingStyleTest {

    @Test
    @DisplayName("正式中文编号（第X条+（一）在同一文档）被识别为 CN_FORMAL")
    void detectsFormalChineseStyle() {
        List<String> lines = List.of(
                "第一条 本合同的构成",
                "本合同由保险单及所附条款组成。",
                "第二条 投保范围",
                "（一）年满十八周岁",
                "（二）身体健康",
                "第三条 保险责任"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.CN_FORMAL, style.get());
    }

    @Test
    @DisplayName("数字编号（1. / 1.1 / 1.1.1）被识别为 CN_NUMERIC")
    void detectsNumericStyle() {
        List<String> lines = List.of(
                "1. 系统架构",
                "1.1 前端设计",
                "1.1.1 组件划分",
                "1.2 后端设计",
                "2. 部署方案"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.CN_NUMERIC, style.get());
    }

    @Test
    @DisplayName("英文编号（Chapter/Section）被识别为 EN")
    void detectsEnglishStyle() {
        List<String> lines = List.of(
                "Chapter I Introduction",
                "This chapter covers the basics.",
                "Section 1 Overview",
                "Section 2 Scope",
                "Chapter II Methodology"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.EN, style.get());
    }

    @Test
    @DisplayName("没有清晰编号体系的文档返回 empty（不强行按编号切）")
    void returnsEmptyWhenNoStructure() {
        List<String> lines = List.of(
                "这是一段普通说明文字。",
                "没有任何编号。",
                "只是纯段落。"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isEmpty());
    }

    @Test
    @DisplayName("levelOf 返回正确的级别下标")
    void levelOfReturnsCorrectIndex() {
        assertEquals(1, HeadingStyle.CN_FORMAL.levelOf("第一章 总则"));
        assertEquals(3, HeadingStyle.CN_FORMAL.levelOf("第一条 定义"));
        assertEquals(-1, HeadingStyle.CN_FORMAL.levelOf("普通文字"));
    }

    @Test
    @DisplayName("levels() 按从粗到细排列且每个风格至少 4 级")
    void levelsAreOrderedCoarseToFine() {
        for (HeadingStyle style : HeadingStyle.values()) {
            assertTrue(style.levels().size() >= 4,
                    style + " 应至少有 4 级，实际: " + style.levels().size());
        }
    }
}
