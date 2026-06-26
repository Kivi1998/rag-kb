package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.Document;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.DocumentService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * 文档控制器(需认证+租户上下文)
 */
@RestController
@RequestMapping("/api/v1/knowledge-bases/{kbId}/documents")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    /**
     * 上传文档(multipart/form-data)
     */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Document> upload(@PathVariable UUID kbId,
                                        @RequestParam("file") MultipartFile file) {
        return ApiResponse.ok(documentService.upload(
                kbId, TenantContext.getOrgId(), TenantContext.getMemberId(), file));
    }

    /**
     * 列出知识库下文档
     */
    @GetMapping
    public ApiResponse<List<Document>> list(@PathVariable UUID kbId) {
        return ApiResponse.ok(documentService.listByKb(kbId, TenantContext.getOrgId()));
    }

    /**
     * 查询单文档详情(含查时刷新)
     */
    @GetMapping("/{docId}")
    public ApiResponse<Document> getById(@PathVariable UUID kbId,
                                         @PathVariable UUID docId) {
        return ApiResponse.ok(documentService.getById(docId, kbId, TenantContext.getOrgId()));
    }

    /**
     * 删除文档(需 owner/admin)
     */
    @DeleteMapping("/{docId}")
    public ApiResponse<Void> delete(@PathVariable UUID kbId,
                                    @PathVariable UUID docId) {
        documentService.delete(docId, kbId, TenantContext.getOrgId(), TenantContext.getRole());
        return ApiResponse.ok();
    }
}
