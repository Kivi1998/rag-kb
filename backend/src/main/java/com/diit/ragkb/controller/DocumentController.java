package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.service.DocumentIngestionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/** 与前端 documentsApi 对齐的文档摄取 HTTP 契约。 */
@RestController
@RequestMapping("/api/v1/documents")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentIngestionService documentService;

    @GetMapping
    public ApiResponse<List<DocumentIngestionService.DocumentView>> list(
            @RequestParam UUID kbId,
            @RequestParam(required = false) IngestionStatus status) {
        return ApiResponse.ok(documentService.list(kbId, status));
    }

    @PostMapping(value = "/upload", consumes = "multipart/form-data")
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<DocumentIngestionService.DocumentView> upload(
            @RequestParam UUID kbId,
            @RequestPart("file") MultipartFile file) {
        return ApiResponse.ok(documentService.upload(kbId, file).document());
    }

    @GetMapping("/jobs/{jobId}")
    public ApiResponse<DocumentIngestionService.JobView> getJob(
            @RequestParam UUID kbId, @PathVariable UUID jobId) {
        return ApiResponse.ok(documentService.getJob(kbId, jobId));
    }

    @PostMapping("/jobs/{jobId}/retry")
    public ApiResponse<DocumentIngestionService.JobView> retry(
            @RequestParam UUID kbId, @PathVariable UUID jobId) {
        return ApiResponse.ok(documentService.retry(kbId, jobId));
    }

    @DeleteMapping("/{documentId}")
    public ApiResponse<Void> delete(@RequestParam UUID kbId, @PathVariable UUID documentId) {
        documentService.delete(kbId, documentId);
        return ApiResponse.ok();
    }
}
