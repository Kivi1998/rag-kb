package com.diit.ragkb.ragcore.intent;

import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import lombok.extern.slf4j.Slf4j;

import java.util.Objects;

/**
 * 用 LLM Prompt 做检索意图粗分类（冷启动路径）：先用 Prompt 上线，线上积累真实 query 后
 * 再训练 BERT 分类器替换。分类器本身未经过任何真实准确率验证，调用失败或输出不可解析时
 * fail-open 返回 {@link QueryIntent#UNKNOWN}，不重试、不阻断问答主流程。
 */
@Slf4j
public class LlmQueryIntentClassifier implements QueryIntentClassifier {

    private static final String SYSTEM_PROMPT = """
            你是一个检索意图分类器。给定用户的一个检索问题，判断它属于以下四类中的哪一类：

            - precise-lookup：问题包含具体的错误码、型号、参数名、专有名词、编号等精确定位信息，
              用户在找一个具体、明确存在的东西
            - semantic：问题是概念性的、宽泛的"是什么/为什么/怎么样"式提问，没有具体定位信息
            - comparative：问题涉及比较两个或以上的实体、方法、方案的异同或优劣
            - out-of-scope：问题与文档内容无关（闲聊、问候、与知识库主题无关的话题），
              或者问题含糊到无法归入前三类

            只输出上面四个标签中的一个（precise-lookup / semantic / comparative / out-of-scope），
            不要输出任何解释、标点、引号或其他文字。

            示例：
            问题：NullPointerException 怎么排查？
            输出：precise-lookup

            问题：为什么要用 L1 范数代替 L0 范数？
            输出：semantic

            问题：RPCA 和 PCA 的区别是什么？
            输出：comparative

            问题：今天天气怎么样？
            输出：out-of-scope""";

    private final ChatCompletionClient chatCompletionClient;

    public LlmQueryIntentClassifier(ChatCompletionClient chatCompletionClient) {
        this.chatCompletionClient = Objects.requireNonNull(chatCompletionClient, "chatCompletionClient 不能为空");
    }

    @Override
    public QueryIntent classify(String question) {
        if (question == null || question.isBlank()) {
            return QueryIntent.UNKNOWN;
        }
        try {
            String userPrompt = "问题：" + question + "\n输出：";
            String raw = chatCompletionClient.complete(SYSTEM_PROMPT, userPrompt);
            QueryIntent intent = parse(raw);
            if (intent == QueryIntent.UNKNOWN) {
                log.warn("查询意图分类输出无法解析，回退为 UNKNOWN，rawOutputLength={}",
                        raw == null ? 0 : raw.length());
            }
            return intent;
        } catch (RuntimeException ex) {
            log.warn("查询意图分类调用失败，回退为 UNKNOWN: {}", ex.getMessage());
            return QueryIntent.UNKNOWN;
        }
    }

    private QueryIntent parse(String raw) {
        if (raw == null) {
            return QueryIntent.UNKNOWN;
        }
        String label = raw.strip().toLowerCase(java.util.Locale.ROOT);
        return switch (label) {
            case "precise-lookup" -> QueryIntent.PRECISE_LOOKUP;
            case "semantic" -> QueryIntent.SEMANTIC;
            case "comparative" -> QueryIntent.COMPARATIVE;
            case "out-of-scope" -> QueryIntent.OUT_OF_SCOPE;
            default -> QueryIntent.UNKNOWN;
        };
    }
}
