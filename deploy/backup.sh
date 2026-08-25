#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env.production"

set -a
source "${ENV_FILE}"
set +a

: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${DATA_DIR:?DATA_DIR is required}"
: "${DB_NAME:?DB_NAME is required}"

if [[ ! "${BACKUP_DIR}" = /* || "${BACKUP_DIR}" == "/" ]]; then
  echo "BACKUP_DIR must be an absolute directory other than /."
  exit 1
fi
if [[ ! "${DATA_DIR}" = /* || "${DATA_DIR}" == "/" ]]; then
  echo "DATA_DIR must be an absolute directory other than /."
  exit 1
fi

retention_days="${BACKUP_RETENTION_DAYS:-30}"
if [[ ! "${retention_days}" =~ ^[0-9]+$ ]]; then
  echo "BACKUP_RETENTION_DAYS must be a non-negative integer."
  exit 1
fi

umask 077
timestamp="$(date +%Y%m%d-%H%M%S)"
target="${BACKUP_DIR}/${timestamp}"
working="${target}.incomplete"
mkdir -p "${working}"
trap 'rm -rf -- "${working}"' EXIT

cd "${PROJECT_DIR}"
docker compose --env-file "${ENV_FILE}" exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --single-transaction --routines --triggers -u root "$MYSQL_DATABASE"' \
  > "${working}/database.sql"

tar -C "${DATA_DIR}" -czf "${working}/audio-exports.tar.gz" audio exports
(
  cd "${working}"
  sha256sum database.sql audio-exports.tar.gz > SHA256SUMS
)
mv "${working}" "${target}"
trap - EXIT

find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d \
  -name "20??????-??????" -mtime "+${retention_days}" \
  -print -exec rm -rf -- {} +
echo "Backup completed: ${target}"
