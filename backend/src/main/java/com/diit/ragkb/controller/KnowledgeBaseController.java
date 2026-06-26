package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.service.KnowledgeBaseService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 知识库控制器(需认证+租户上下文)
 */
@RestController
@RequestMapping("/api/v1/knowledge-bases")
@RequiredArgsConstructor
public class KnowledgeBaseController {

    private final KnowledgeBaseService kbService;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<KnowledgeBase> create(@Valid @RequestBody CreateKbRequest req) {
        return ApiResponse.ok(kbService.create(req.getName()));
    }

    @GetMapping
    public ApiResponse<List<KnowledgeBase>> list() {
        return ApiResponse.ok(kbService.listByCurrentOrg());
    }

    @GetMapping("/{id}")
    public ApiResponse<KnowledgeBase> getById(@PathVariable("id") UUID id) {
        return ApiResponse.ok(kbService.getByIdAndCurrentOrg(id));
    }

    @PatchMapping("/{id}")
    public ApiResponse<KnowledgeBase> update(@PathVariable("id") UUID id,
                                             @Valid @RequestBody UpdateKbRequest req) {
        return ApiResponse.ok(kbService.update(id, req.getName()));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<String> delete(@PathVariable("id") UUID id) {
        boolean fullyDeleted = kbService.delete(id);
        if (fullyDeleted) {
            return ApiResponse.ok("已删除");
        } else {
            return ApiResponse.fail(202, "知识库已标记待清理(dataset 删除失败,将由对账任务处理)");
        }
    }

    @Data
    public static class CreateKbRequest {
        @NotBlank(message = "知识库名称不能为空")
        private String name;
    }

    @Data
    public static class UpdateKbRequest {
        @NotBlank(message = "知识库名称不能为空")
        private String name;
    }
}
