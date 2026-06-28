package com.diit.ragkb.config;

import com.diit.ragkb.security.TenantContext;
import jakarta.persistence.EntityManager;
import org.hibernate.Filter;
import org.hibernate.Session;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Hibernate @Filter 激活器:每个事务自动注入 org_id 过滤
 * 作为"元数据层第二保险"——即使应用层遗漏 WHERE org_id,此过滤器仍拦截
 */
@Component
public class TenantHibernateFilterConfig {

    private static final String FILTER_NAME = "tenantFilter";

    /**
     * 在当前 Session 上启用租户过滤器
     * 调用时机:Service 方法进入事务后
     */
    public void enableFilter(EntityManager entityManager) {
        UUID orgId = TenantContext.getOrgId();
        if (orgId == null) {
            return; // 免租户上下文的端点不注入
        }
        Session session = entityManager.unwrap(Session.class);
        Filter filter = session.enableFilter(FILTER_NAME);
        filter.setParameter("orgId", orgId);
    }
}
