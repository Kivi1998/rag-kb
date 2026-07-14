package com.diit.ragkb.ragcore.chunk.impl;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 一套文档编号风格：由粗到细排列的多级正则，覆盖同一份文档常见的编号写法。
 *
 * <p>用于在切分前先扫一遍全文，自动选出命中次数最多的一套风格，而不是像
 * 旧版那样对所有文档都用同一套死板正则。思路参考 RAGFlow deepdoc 的
 * {@code bullets_category()}（多套候选正则 + 统计命中数选优），
 * 正则集合与选择逻辑是本项目独立设计实现，不是移植代码。</p>
 */
enum HeadingStyle {

    /** 正式合同/法规常见：第X编/章/节/条，(一)(二) */
    CN_FORMAL(List.of(
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+章"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+节"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+(编|部分)"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+条"),
            Pattern.compile("^[（(][零一二三四五六七八九十0-9]+[）)]")
    )),

    /** 技术文档/报告常见：第X章/节，1. / 1.1 / 1.1.1 */
    CN_NUMERIC(List.of(
            Pattern.compile("^第[0-9]+章"),
            Pattern.compile("^第[0-9]+节"),
            Pattern.compile("^[0-9]{1,2}[、.．][^0-9]"),
            Pattern.compile("^[0-9]{1,2}\\.[0-9]{1,2}(?!\\.[0-9])"),
            Pattern.compile("^[0-9]{1,2}\\.[0-9]{1,2}\\.[0-9]{1,2}")
    )),

    /** 非正式文档常见：第X章/节，一、二、，（一）（1） */
    CN_INFORMAL(List.of(
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+章"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+节"),
            Pattern.compile("^[一二三四五六七八九十]+[、.]"),
            Pattern.compile("^[（(][一二三四五六七八九十]+[）)]"),
            Pattern.compile("^[（(][0-9]{1,2}[）)]")
    )),

    /** 英文文档：Part/Chapter/Section/Article */
    EN(List.of(
            Pattern.compile("(?i)^part (one|two|three|four|five|six|seven|eight|nine|ten)"),
            Pattern.compile("(?i)^chapter [ivxlcdm]+"),
            Pattern.compile("(?i)^section [0-9]+"),
            Pattern.compile("(?i)^article [0-9]+")
    ));

    private final List<Pattern> levels;

    HeadingStyle(List<Pattern> levels) {
        this.levels = levels;
    }

    List<Pattern> levels() {
        return levels;
    }

    /** 该行命中的最细级别下标（0 = 最粗）；未命中任何级别返回 -1。 */
    int levelOf(String line) {
        String stripped = line.strip();
        if (stripped.isEmpty()) return -1;
        for (int i = 0; i < levels.size(); i++) {
            if (levels.get(i).matcher(stripped).find()) {
                return i;
            }
        }
        return -1;
    }

    private int countMatches(List<String> lines) {
        int count = 0;
        for (String line : lines) {
            if (levelOf(line) >= 0) count++;
        }
        return count;
    }

    /**
     * 扫描全文，返回命中次数最多的风格；如果最高命中数低于 minHits，
     * 说明文档没有清晰的编号体系，返回 empty，调用方应退化为不强制按结构切分。
     */
    static Optional<HeadingStyle> detectDominant(List<String> lines, int minHits) {
        HeadingStyle best = null;
        int bestCount = 0;
        for (HeadingStyle style : values()) {
            int count = style.countMatches(lines);
            if (count > bestCount) {
                best = style;
                bestCount = count;
            }
        }
        if (best == null || bestCount < minHits) {
            return Optional.empty();
        }
        return Optional.of(best);
    }
}
