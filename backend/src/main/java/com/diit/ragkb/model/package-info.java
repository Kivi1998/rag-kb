/**
 * 租户实体包
 *
 * 全局 Hibernate @FilterDef:tenantFilter
 * 按 org_id 过滤,由 TenantHibernateFilterConfig 在请求开始时激活
 */
@FilterDef(name = "tenantFilter", parameters = @ParamDef(name = "orgId", type = java.util.UUID.class))
package com.diit.ragkb.model;

import org.hibernate.annotations.FilterDef;
import org.hibernate.annotations.ParamDef;
