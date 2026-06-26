package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.service.OrganizationService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

/**
 * 组织控制器
 *
 * POST /api/v1/organizations = bootstrap(免租户上下文,白名单放行)
 * GET  /api/v1/organizations/{id} = 需认证+租户上下文
 */
@RestController
@RequestMapping("/api/v1/organizations")
@RequiredArgsConstructor
public class OrganizationController {

    private final OrganizationService orgService;

    /**
     * 创建组织(免租户上下文,但需有效 JWT)
     * subject 从 JwtAuthFilter 设置的 request attribute 获取(已验证 JWT 签名)
     */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Organization> create(
            jakarta.servlet.http.HttpServletRequest request,
            @Valid @RequestBody CreateOrgRequest req) {
        String subjectId = (String) request.getAttribute("subjectId");
        return ApiResponse.ok(orgService.create(subjectId, req.getName()));
    }

    @GetMapping("/{id}")
    public ApiResponse<Organization> getById(@PathVariable("id") java.util.UUID id) {
        return ApiResponse.ok(orgService.getById(id));
    }

    @Data
    public static class CreateOrgRequest {
        @NotBlank(message = "组织名称不能为空")
        private String name;
    }
}
