package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.Team;
import com.diit.ragkb.service.TeamService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 团队控制器(需认证+租户上下文)
 */
@RestController
@RequestMapping("/api/v1/teams")
@RequiredArgsConstructor
public class TeamController {

    private final TeamService teamService;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Team> create(@Valid @RequestBody CreateTeamRequest req) {
        return ApiResponse.ok(teamService.create(req.getName()));
    }

    @GetMapping
    public ApiResponse<List<Team>> list() {
        return ApiResponse.ok(teamService.listByCurrentOrg());
    }

    @GetMapping("/{id}")
    public ApiResponse<Team> getById(@PathVariable("id") UUID id) {
        return ApiResponse.ok(teamService.getByIdAndCurrentOrg(id));
    }

    @Data
    public static class CreateTeamRequest {
        @NotBlank(message = "团队名称不能为空")
        private String name;
    }
}
