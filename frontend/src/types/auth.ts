/** 登录响应 DTO */
export interface LoginResponse {
  token: string
  userId: string
  orgId: string | null
  mustChangePassword?: boolean
}

/** 认证状态 */
export interface AuthState {
  token: string | null
  username: string | null
  orgId: string | null
}
