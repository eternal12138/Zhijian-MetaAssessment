import type { AppRole } from '../stores/auth'

export function roleHome(role: AppRole | null | undefined) {
  if (role === 'teacher' || role === 'admin') return '/teacher'
  return '/'
}
