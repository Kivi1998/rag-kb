# knowledge-base Specification

## Purpose
TBD - created by archiving change tenant-kb-foundation. Update Purpose after archive.
## Requirements
### Requirement: 知识库 CRUD

系统 SHALL 允许有权限的成员在其组织内创建、查询、更新、删除知识库。每个知识库 MUST 归属唯一组织,可选归属某团队。

#### Scenario: 创建知识库

- **WHEN** admin 在其组织内创建名为 X 的知识库
- **THEN** 系统持久化知识库,记录其组织归属与创建者

#### Scenario: 授权更新知识库

- **WHEN** owner 或 admin 更新本组织知识库的名称/描述
- **THEN** 系统持久化更新;dataset 绑定关系不变

#### Scenario: 删除知识库级联清理

- **WHEN** 有权限成员删除一个知识库
- **THEN** 系统按"先删 RAGFlow dataset、再删业务库记录"的顺序级联清理,全部成功才算完成

#### Scenario: 删除时 dataset 清理失败转入对账

- **WHEN** 删除过程中 RAGFlow dataset 删除失败
- **THEN** 系统不留下指向已失效 dataset 的悬挂记录:将该知识库标记为"待清理"并转入孤儿对账,由对账任务最终删除 dataset 与记录,接口返回明确错误

### Requirement: 知识库与 RAGFlow dataset 映射

系统 SHALL 在创建知识库时,通过 RAGFlow REST 接口创建一个**独立 dataset**,并持久化"知识库 ID ↔ dataset ID"映射。每个知识库 MUST 对应专属 dataset,不得多个知识库共用同一 dataset。

系统创建 dataset 时 MUST 带可识别本产品归属的命名前缀/标签(如 `ragkb:<org_id>:<kb_id>`),以便对账时区分本产品 dataset 与 RAGFlow 上的其他 dataset。dataset 创建调用 MUST 幂等(携带幂等键或重试前查重),避免超时重试产生重复 dataset。

#### Scenario: 创建即开专属 dataset

- **WHEN** 知识库创建成功
- **THEN** 系统已为其创建带归属标签的专属 RAGFlow dataset,并保存知识库与 dataset 的映射

#### Scenario: dataset 创建失败整体回滚

- **WHEN** RAGFlow dataset 创建失败
- **THEN** 系统不保留半成品知识库记录(整体失败/回滚),并返回错误

#### Scenario: 创建超时重试不产生重复 dataset

- **WHEN** dataset 创建请求超时后被重试
- **THEN** 凭幂等键/查重确保最终只存在一个 dataset,不产生重复

### Requirement: 知识库级 RBAC

系统 SHALL 在每个知识库访问路径强制校验:调用者 MUST 属于知识库所属组织,且其角色满足该操作。owner 与 admin SHALL 可管理(增删改),member 默认可读。

#### Scenario: 授权读取

- **WHEN** 组织内 member 读取本组织的知识库
- **THEN** 系统返回知识库内容

#### Scenario: 越权写入被拒

- **WHEN** member 尝试删除知识库
- **THEN** 系统返回 403,知识库不被删除

### Requirement: 知识库跨租户隔离(安全红线)

系统 MUST 确保成员无法访问、列举或操作其他组织的知识库及其 RAGFlow dataset。

#### Scenario: 跨组织访问知识库按不存在处理

- **WHEN** 组织 A 的成员按 ID 直取组织 B 的知识库
- **THEN** 系统返回 404(按"资源不存在"处理),绝不返回内容,也不访问对方的 dataset,不泄露其是否存在

#### Scenario: 列举仅限本组织知识库

- **WHEN** 成员列举知识库
- **THEN** 结果只包含其所属组织的知识库

