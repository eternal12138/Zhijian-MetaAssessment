/** Shared predicates kept separate so deployment recovery can be unit tested. */
export const chunkLoadFailurePattern = /(?:Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk [\w-]+ failed|ChunkLoadError)/i

export function isChunkLoadFailure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  return chunkLoadFailurePattern.test(message)
}
