/**
 * 认证相关 API
 */
import apiClient from './client'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: {
    id: string
    username: string
    role: string
    name: string
    avatar_text?: string
    class_group?: string | null
    managed_classes?: string | null
    must_change_password: boolean
  }
}

export const authApi = {
  /** 登录获取 JWT */
  login(data: LoginRequest) {
    return apiClient.post<LoginResponse>('/auth/login', data)
  },

  /** 获取当前用户信息 */
  me() {
    return apiClient.get('/users/me')
  },

  /** 确认暂时继续使用当前密码 */
  skipPasswordChange() {
    return apiClient.post<LoginResponse>('/auth/skip-password-change')
  }
}
