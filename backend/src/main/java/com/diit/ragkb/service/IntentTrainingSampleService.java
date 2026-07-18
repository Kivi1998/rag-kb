package com.diit.ragkb.service;

import com.diit.ragkb.model.IntentTrainingSample;
import com.diit.ragkb.repository.IntentTrainingSampleRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * 意图分类训练数据留存：把「问题原文 + 预测意图标签」样本落库，供未来训练 BERT 分类器使用。
 * 只在意图分类成功产出合法标签时才有意义写入，调用方（{@code QueryController}）负责判断。
 *
 * <p>不用 {@code @Service} 自动扫描——bean 是否存在由 {@code rag.intent-training-data.enabled}
 * 门控（见 {@code RagQueryConfiguration}），未开启时 {@code ObjectProvider} 取不到实例。</p>
 */
@Slf4j
@RequiredArgsConstructor
public class IntentTrainingSampleService {

    private final IntentTrainingSampleRepository repository;

    /** 落库失败不得影响问答主流程——这张表是数据积累，不是问答必需环节。 */
    public void recordSafely(UUID orgId, UUID kbId, UUID memberId, String question, String predictedIntent) {
        try {
            record(orgId, kbId, memberId, question, predictedIntent);
        } catch (RuntimeException ex) {
            log.error("意图训练样本落库失败 orgId={} errorType={}", orgId, ex.getClass().getSimpleName());
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(UUID orgId, UUID kbId, UUID memberId, String question, String predictedIntent) {
        IntentTrainingSample entity = new IntentTrainingSample();
        entity.setOrgId(orgId);
        entity.setKbId(kbId);
        entity.setMemberId(memberId);
        entity.setQuestion(question);
        entity.setPredictedIntent(predictedIntent);
        repository.save(entity);
        // 不含问题原文——同 QueryAuditService 的落库日志一样，只记标识和标签方便排查。
        log.info("intent_training_sample orgId={} kbId={} memberId={} predictedIntent={}", orgId, kbId, memberId,
                predictedIntent);
    }
}
