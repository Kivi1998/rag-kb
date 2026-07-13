package com.diit.ragkb.exception;

import com.diit.ragkb.common.ApiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

/**
 * 全局异常处理
 *
 * 错码约定(与 OpenSpec design 对齐):
 * - 400: 参数非法 / 业务校验失败
 * - 401: 未认证
 * - 403: 同租户内角色权限不足
 * - 404: 资源不存在(含跨租户——对其他组织资源一律按不存在处理)
 * - 409: 业务不变量冲突(如:降级最后一名 owner)
 * - 500: 服务端内部错误(非业务异常)
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 参数非法(400) */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidation(MethodArgumentNotValidException ex) {
        String msg = ex.getBindingResult().getFieldErrors().stream()
                .map(e -> e.getField() + ": " + e.getDefaultMessage())
                .reduce((a, b) -> a + "; " + b)
                .orElse("参数校验失败");
        return ResponseEntity.badRequest().body(ApiResponse.fail(400, msg));
    }

    /** 参数非法 / 业务校验失败(400) */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiResponse<Void>> handleIllegalArgument(IllegalArgumentException ex) {
        return ResponseEntity.badRequest().body(ApiResponse.fail(400, ex.getMessage()));
    }

    /** 查询参数或路径参数无法转换（例如未知摄取状态）(400)。 */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiResponse<Void>> handleTypeMismatch(MethodArgumentTypeMismatchException ex) {
        return ResponseEntity.badRequest().body(ApiResponse.fail(400, "参数格式不合法: " + ex.getName()));
    }

    /** 未认证(401) */
    @ExceptionHandler(UnauthenticatedException.class)
    public ResponseEntity<ApiResponse<Void>> handleUnauthenticated(UnauthenticatedException ex) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ApiResponse.fail(401, ex.getMessage()));
    }

    /** 同租户内角色权限不足(403) */
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ApiResponse<Void>> handleAccessDenied(AccessDeniedException ex) {
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(ApiResponse.fail(403, ex.getMessage()));
    }

    /** 账号已锁定(423) */
    @ExceptionHandler(AccountLockedException.class)
    public ResponseEntity<ApiResponse<Void>> handleAccountLocked(AccountLockedException ex) {
        return ResponseEntity.status(423)
                .body(ApiResponse.fail(423, ex.getMessage()));
    }

    /** 资源不存在(404) —— 含跨租户(对其他组织资源一律按不存在处理) */
    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNotFound(ResourceNotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.fail(404, ex.getMessage()));
    }

    /** 业务不变量冲突(409) */
    @ExceptionHandler(BusinessConflictException.class)
    public ResponseEntity<ApiResponse<Void>> handleConflict(BusinessConflictException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ApiResponse.fail(409, ex.getMessage()));
    }

    /** 数据库唯一约束或关联约束冲突(409)，避免并发幂等请求泄漏为 500。 */
    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleDataIntegrityViolation(DataIntegrityViolationException ex) {
        log.info("数据完整性冲突", ex);
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ApiResponse.fail(409, "请求与已有数据冲突，请使用相同参数重试或更换幂等键"));
    }

    /** 文件超过大小限制(413 Payload Too Large) */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ApiResponse<Void>> handleMaxUploadSize(MaxUploadSizeExceededException ex) {
        return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE)
                .body(ApiResponse.fail(413, "文件大小超过服务端上传限制"));
    }

    /** 服务端内部错误兜底(500) */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleUnknown(Exception ex) {
        log.error("未捕获异常", ex);
        return ResponseEntity.internalServerError()
                .body(ApiResponse.fail(500, "服务内部错误"));
    }
}
