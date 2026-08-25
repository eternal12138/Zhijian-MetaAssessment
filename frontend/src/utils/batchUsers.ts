import type { CreateUserRequest } from '../api/admin'

const ROLE_ALIASES: Record<string, 'student' | 'teacher' | 'admin'> = {
  student: 'student',
  teacher: 'teacher',
  admin: 'admin',
  学生: 'student',
  教师: 'teacher',
  老师: 'teacher',
  管理员: 'admin'
}

export interface BatchUserParseResult {
  users: CreateUserRequest[]
  errors: string[]
}

function splitRow(row: string): string[] {
  const cells: string[] = []
  let cell = ''
  let quoted = false

  for (let index = 0; index < row.length; index += 1) {
    const character = row[index]
    if (character === '"') {
      if (quoted && row[index + 1] === '"') {
        cell += '"'
        index += 1
      } else {
        quoted = !quoted
      }
      continue
    }
    if (!quoted && (character === ',' || character === '，' || character === '\t')) {
      cells.push(cell.trim())
      cell = ''
      continue
    }
    cell += character
  }
  cells.push(cell.trim())
  return cells
}

function isHeader(cells: string[]): boolean {
  const first = (cells[0] || '').replace(/^\uFEFF/, '').toLowerCase()
  return ['账号', '学号', '工号', 'username', 'account'].includes(first)
}

export function parseBatchUsers(text: string): BatchUserParseResult {
  const users: CreateUserRequest[] = []
  const errors: string[] = []
  const usernames = new Set<string>()
  const rows = text.replace(/^\uFEFF/, '').split(/\r?\n/)

  rows.forEach((rawRow, rowIndex) => {
    const lineNumber = rowIndex + 1
    const row = rawRow.trim()
    if (!row) return

    const cells = splitRow(row)
    if (isHeader(cells)) return
    if (cells.length > 4) {
      errors.push(`第 ${lineNumber} 行超过 4 列；多个负责班级请使用“|”或“；”分隔`)
      return
    }

    const username = (cells[0] || '').replace(/^\uFEFF/, '').trim()
    const name = (cells[1] || '').trim()
    const roleText = (cells[2] || 'student').trim().toLowerCase()
    const role = ROLE_ALIASES[roleText]
    const classValue = (cells[3] || '').trim()

    if (!username || !name) {
      errors.push(`第 ${lineNumber} 行的账号和姓名不能为空`)
      return
    }
    if (!role) {
      errors.push(`第 ${lineNumber} 行角色“${cells[2]}”无效`)
      return
    }
    if (usernames.has(username)) {
      errors.push(`第 ${lineNumber} 行账号 ${username} 重复`)
      return
    }
    usernames.add(username)
    users.push({
      username,
      name,
      role,
      password: '123456',
      class_group: role === 'student' ? classValue : null,
      managed_classes: role === 'teacher' ? classValue : null
    })
  })

  return { users, errors }
}
