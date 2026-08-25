export type OfflineUploadStatus = 'pending' | 'uploading' | 'failed' | 'synced'

export interface OfflineAssessmentSnapshot {
  id: string
  userId: string
  runId: string
  protocolId: string
  currentPhase: string
  currentTaskIndex: number
  practiceAnswer: string
  practiceCompleted: boolean
  questionnaireAnswers: Record<string, number>
  participantName: string
  activeSessionId: string | null
  updatedAt: number
  checksum: string
  status: 'active' | 'completed'
}

interface OfflineSyncRecord {
  id: string
  userId: string
  runId: string
  sessionId: string
  uploadStatus: OfflineUploadStatus
  retryCount: number
  lastError: string
  updatedAt: number
}

export interface OfflineAudioChunk extends OfflineSyncRecord {
  chunkIndex: number
  blob: Blob
  mimeType: string
  startedAtMs: number
  endedAtMs: number
}

export interface OfflineTranscriptSegment extends OfflineSyncRecord {
  segmentId: string
  text: string
  startedAtMs: number
  endedAtMs: number
}

export interface OfflineInteractionEvent extends OfflineSyncRecord {
  eventId: string
  event: Record<string, unknown>
}

const DB_NAME = 'Zhijian_Assessment_Offline_DB'
const DB_VERSION = 1
const SNAPSHOT_STORE = 'assessment_snapshots'
const AUDIO_STORE = 'pending_audio_chunks'
const TRANSCRIPT_STORE = 'pending_transcripts'
const EVENT_STORE = 'pending_interaction_events'
const SNAPSHOT_FALLBACK_PREFIX = 'zhijian-assessment-snapshot:'

let databasePromise: Promise<IDBDatabase> | null = null
let indexedDbUnavailable = false
const memoryAudio = new Map<string, OfflineAudioChunk>()
const memoryTranscripts = new Map<string, OfflineTranscriptSegment>()
const memoryEvents = new Map<string, OfflineInteractionEvent>()

function requestResult<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB 请求失败'))
  })
}

function transactionDone(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB 事务失败'))
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB 事务已中止'))
  })
}

function ensureIndexes(store: IDBObjectStore) {
  if (!store.indexNames.contains('userId')) store.createIndex('userId', 'userId')
  if (!store.indexNames.contains('runId')) store.createIndex('runId', 'runId')
  if (!store.indexNames.contains('sessionId')) store.createIndex('sessionId', 'sessionId')
  if (!store.indexNames.contains('status')) store.createIndex('status', 'uploadStatus')
  if (!store.indexNames.contains('userRun')) store.createIndex('userRun', ['userId', 'runId'])
}

function openDatabase() {
  if (indexedDbUnavailable || typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('当前浏览器不可使用 IndexedDB'))
  }
  if (databasePromise) return databasePromise
  databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) {
        const snapshots = db.createObjectStore(SNAPSHOT_STORE, { keyPath: 'id' })
        snapshots.createIndex('userId', 'userId')
        snapshots.createIndex('runId', 'runId')
        snapshots.createIndex('status', 'status')
        snapshots.createIndex('userRun', ['userId', 'runId'], { unique: true })
      }
      for (const storeName of [AUDIO_STORE, TRANSCRIPT_STORE, EVENT_STORE]) {
        const store = db.objectStoreNames.contains(storeName)
          ? request.transaction!.objectStore(storeName)
          : db.createObjectStore(storeName, { keyPath: 'id' })
        ensureIndexes(store)
      }
    }
    request.onsuccess = () => {
      const db = request.result
      db.onversionchange = () => db.close()
      resolve(db)
    }
    request.onerror = () => {
      indexedDbUnavailable = true
      databasePromise = null
      reject(request.error ?? new Error('无法打开离线测评数据库'))
    }
    request.onblocked = () => reject(new Error('离线测评数据库升级被其他页面阻塞'))
  })
  return databasePromise
}

async function putRecord<T>(storeName: string, record: T) {
  const db = await openDatabase()
  const transaction = db.transaction(storeName, 'readwrite')
  transaction.objectStore(storeName).put(record)
  await transactionDone(transaction)
}

async function deleteRecord(storeName: string, id: string) {
  const db = await openDatabase()
  const transaction = db.transaction(storeName, 'readwrite')
  transaction.objectStore(storeName).delete(id)
  await transactionDone(transaction)
}

async function recordsForRun<T>(storeName: string, userId: string, runId: string) {
  const db = await openDatabase()
  const transaction = db.transaction(storeName, 'readonly')
  const request = transaction
    .objectStore(storeName)
    .index('userRun')
    .getAll(IDBKeyRange.only([userId, runId]))
  const records = await requestResult(request)
  await transactionDone(transaction)
  return records as T[]
}

function fallbackSnapshotKey(userId: string, runId: string) {
  return `${SNAPSHOT_FALLBACK_PREFIX}${userId}:${runId}`
}

function stableChecksum(value: unknown) {
  const text = JSON.stringify(value)
  let hash = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function fallbackSnapshot(snapshot: OfflineAssessmentSnapshot) {
  try {
    localStorage.setItem(fallbackSnapshotKey(snapshot.userId, snapshot.runId), JSON.stringify(snapshot))
  } catch {
    // 隐私模式可能同时禁用 IndexedDB 与 localStorage，调用方会显示降级提醒。
  }
}

function readFallbackSnapshot(userId: string, runId: string) {
  try {
    const raw = localStorage.getItem(fallbackSnapshotKey(userId, runId))
    return raw ? JSON.parse(raw) as OfflineAssessmentSnapshot : null
  } catch {
    return null
  }
}

export function createSnapshot(input: Omit<OfflineAssessmentSnapshot, 'id' | 'updatedAt' | 'checksum'>) {
  const updatedAt = Date.now()
  const snapshot = {
    ...input,
    id: `${input.userId}:${input.runId}`,
    updatedAt,
    checksum: ''
  }
  snapshot.checksum = stableChecksum({ ...snapshot, checksum: undefined })
  return snapshot
}

export async function saveAssessmentSnapshot(snapshot: OfflineAssessmentSnapshot) {
  fallbackSnapshot(snapshot)
  try {
    await putRecord(SNAPSHOT_STORE, snapshot)
    return true
  } catch {
    return false
  }
}

export async function getAssessmentSnapshot(userId: string, runId: string) {
  try {
    const db = await openDatabase()
    const transaction = db.transaction(SNAPSHOT_STORE, 'readonly')
    const result = await requestResult(
      transaction.objectStore(SNAPSHOT_STORE).get(`${userId}:${runId}`)
    ) as OfflineAssessmentSnapshot | undefined
    await transactionDone(transaction)
    return result ?? readFallbackSnapshot(userId, runId)
  } catch {
    return readFallbackSnapshot(userId, runId)
  }
}

export async function clearAssessmentSnapshot(userId: string, runId: string) {
  try {
    localStorage.removeItem(fallbackSnapshotKey(userId, runId))
  } catch { /* noop */ }
  try {
    await deleteRecord(SNAPSHOT_STORE, `${userId}:${runId}`)
  } catch { /* IndexedDB 降级时只清理 localStorage。 */ }
}

export function audioChunkRecordId(userId: string, runId: string, sessionId: string, chunkIndex: number) {
  return `${userId}:${runId}:${sessionId}:audio:${chunkIndex}`
}

export async function saveOfflineAudioChunk(record: OfflineAudioChunk) {
  memoryAudio.set(record.id, record)
  try {
    await putRecord(AUDIO_STORE, record)
    return true
  } catch {
    return false
  }
}

export async function saveOfflineTranscript(record: OfflineTranscriptSegment) {
  memoryTranscripts.set(record.id, record)
  try {
    await putRecord(TRANSCRIPT_STORE, record)
    return true
  } catch {
    return false
  }
}

export async function saveOfflineEvent(record: OfflineInteractionEvent) {
  memoryEvents.set(record.id, record)
  try {
    await putRecord(EVENT_STORE, record)
    return true
  } catch {
    return false
  }
}

export async function removeOfflineAudioChunk(id: string) {
  memoryAudio.delete(id)
  try { await deleteRecord(AUDIO_STORE, id) } catch { /* noop */ }
}

export async function removeOfflineTranscript(id: string) {
  memoryTranscripts.delete(id)
  try { await deleteRecord(TRANSCRIPT_STORE, id) } catch { /* noop */ }
}

export async function removeOfflineEvent(id: string) {
  memoryEvents.delete(id)
  try { await deleteRecord(EVENT_STORE, id) } catch { /* noop */ }
}

export async function getPendingAudioChunks(userId: string, runId: string) {
  try {
    return (await recordsForRun<OfflineAudioChunk>(AUDIO_STORE, userId, runId))
      .filter(record => record.uploadStatus !== 'synced')
      .sort((left, right) => left.chunkIndex - right.chunkIndex)
  } catch {
    return [...memoryAudio.values()]
      .filter(record => record.userId === userId && record.runId === runId && record.uploadStatus !== 'synced')
      .sort((left, right) => left.chunkIndex - right.chunkIndex)
  }
}

export async function getPendingTranscripts(userId: string, runId: string) {
  try {
    return (await recordsForRun<OfflineTranscriptSegment>(TRANSCRIPT_STORE, userId, runId))
      .filter(record => record.uploadStatus !== 'synced')
      .sort((left, right) => left.startedAtMs - right.startedAtMs)
  } catch {
    return [...memoryTranscripts.values()]
      .filter(record => record.userId === userId && record.runId === runId && record.uploadStatus !== 'synced')
      .sort((left, right) => left.startedAtMs - right.startedAtMs)
  }
}

export async function getPendingEvents(userId: string, runId: string) {
  try {
    return (await recordsForRun<OfflineInteractionEvent>(EVENT_STORE, userId, runId))
      .filter(record => record.uploadStatus !== 'synced')
      .sort((left, right) => Number(left.event.client_timestamp_ms ?? 0) - Number(right.event.client_timestamp_ms ?? 0))
  } catch {
    return [...memoryEvents.values()]
      .filter(record => record.userId === userId && record.runId === runId && record.uploadStatus !== 'synced')
      .sort((left, right) => Number(left.event.client_timestamp_ms ?? 0) - Number(right.event.client_timestamp_ms ?? 0))
  }
}

export async function clearOfflineRunData(userId: string, runId: string) {
  await clearAssessmentSnapshot(userId, runId)
  for (const [id, record] of memoryAudio) if (record.userId === userId && record.runId === runId) memoryAudio.delete(id)
  for (const [id, record] of memoryTranscripts) if (record.userId === userId && record.runId === runId) memoryTranscripts.delete(id)
  for (const [id, record] of memoryEvents) if (record.userId === userId && record.runId === runId) memoryEvents.delete(id)
  try {
    const db = await openDatabase()
    const transaction = db.transaction([AUDIO_STORE, TRANSCRIPT_STORE, EVENT_STORE], 'readwrite')
    for (const storeName of [AUDIO_STORE, TRANSCRIPT_STORE, EVENT_STORE]) {
      const store = transaction.objectStore(storeName)
      const keys = await requestResult(store.index('userRun').getAllKeys(IDBKeyRange.only([userId, runId])))
      for (const key of keys) store.delete(key)
    }
    await transactionDone(transaction)
  } catch { /* 本地持久层不可用时，内存数据已清理。 */ }
}

export async function checkOfflineStorage() {
  try {
    await openDatabase()
    return { persistent: true, message: '' }
  } catch {
    return {
      persistent: false,
      message: '浏览器无法使用持久化离线存储；文字草稿将尽力保留，但断网时请不要关闭页面。'
    }
  }
}
