package com.diit.ragkb.config;

import com.diit.ragkb.security.TenantContext;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.springframework.stereotype.Component;

/**
 * AOP 切面:在 Service 层方法调用前自动激活 Hibernate @Filter
 *
 * 作为"元数据层第二防线":
 * - 即使 Repository 查询遗漏 WHERE org_id,Hibernate @Filter 仍会拦截
 * - 仅在有租户上下文时激活(bootstrap 端点无上下文,跳过)
 */
@Aspect
@Component
@RequiredArgsConstructor
public class TenantFilterAspect {

    private final TenantHibernateFilterConfig filterConfig;
    private final EntityManager entityManager;

    /** 在所有 Service 方法执行前激活租户过滤器 */
    @Before("execution(* com.diit.ragkb.service..*.*(..))")
    public void enableTenantFilter() {
        filterConfig.enableFilter(entityManager);
    }
}
