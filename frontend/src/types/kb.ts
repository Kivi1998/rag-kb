/** 知识库状态 */
export type KnowledgeBaseStatus = 'ACTIVE' | 'PENDING_CLEANUP'

/** 知识库 DTO */
export interface KnowledgeBase {
  id: string
  name: string
  status: KnowledgeBaseStatus
  createdAt: string
}
