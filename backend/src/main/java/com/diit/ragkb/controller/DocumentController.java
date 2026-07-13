package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.service.DocumentIngestionService;
import com.diit.ragkb.service.DocumentDirectUploadService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
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
    private final DocumentDirectUploadService directUploadService;

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

    /** 为大文件签发 MinIO/S3 直传地址；同一幂等键重复调用返回同一会话。 */
    @PostMapping("/uploads")
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<DocumentDirectUploadService.UploadSessionView> initiateDirectUpload(
            @RequestHeader("Idempotency-Key") @NotBlank String idempotencyKey,
            @RequestBody @Valid InitiateUploadRequest request) {
        return ApiResponse.ok(directUploadService.initiate(
                request.kbId(), request.fileName(), request.sizeBytes(), idempotencyKey));
    }

    /** 客户端 PUT 完成后调用；服务端确认对象存在且大小一致，再原子创建摄取任务。 */
    @PostMapping("/uploads/{sessionId}/complete")
    public ApiResponse<DocumentDirectUploadService.CompletedUploadView> completeDirectUpload(
            @PathVariable UUID sessionId) {
        return ApiResponse.ok(directUploadService.complete(sessionId));
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

    public record InitiateUploadRequest(@NotNull UUID kbId, @NotBlank String fileName, @Positive long sizeBytes) { }
}
