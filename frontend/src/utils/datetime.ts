/** Parse API timestamps according to the system-wide UTC storage contract. */
export function parseApiDate(value: string | number | Date): Date {
  if (typeof value !== 'string') return new Date(value)
  const normalized = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
    ? `${value.replace(' ', 'T')}Z`
    : value
  return new Date(normalized)
}

export function apiDateTimestamp(value: string): number {
  return parseApiDate(value).getTime()
}
