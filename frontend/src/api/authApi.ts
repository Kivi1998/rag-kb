import http from './http'
import type { LoginResponse } from '@/types/auth'

export const authApi = {
  login(email: string, password: string): Promise<LoginResponse> {
    return http.post('/api/v1/auth/login', { email, password })
  }
}
