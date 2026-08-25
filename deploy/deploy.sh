#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env.production"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env.production. Copy .env.production.example and fill it first."
  exit 1
fi

if grep -q "CHANGE_ME" "${ENV_FILE}"; then
  echo ".env.production still contains CHANGE_ME placeholders."
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

: "${DATA_DIR:?DATA_DIR is required}"
: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${PUBLIC_HOST:?PUBLIC_HOST is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${BOOTSTRAP_ADMIN_USERNAME:?BOOTSTRAP_ADMIN_USERNAME is required}"

if [[ ! "${DATA_DIR}" = /* || "${DATA_DIR}" == "/" ]]; then
  echo "DATA_DIR must be an absolute directory other than /."
  exit 1
fi
if [[ ! "${BACKUP_DIR}" = /* || "${BACKUP_DIR}" == "/" ]]; then
  echo "BACKUP_DIR must be an absolute directory other than /."
  exit 1
fi
if [[ ! "${DB_USER}" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DB_USER may only contain letters, digits, and underscores."
  exit 1
fi
if [[ ! "${DB_NAME}" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DB_NAME may only contain letters, digits, and underscores."
  exit 1
fi
if [[ ! "${BOOTSTRAP_ADMIN_USERNAME}" =~ ^[A-Za-z0-9_.-]{2,64}$ ]]; then
  echo "BOOTSTRAP_ADMIN_USERNAME contains invalid characters."
  exit 1
fi
if [[ -n "${BOOTSTRAP_ADMIN_PASSWORD:-}" &&
      ${#BOOTSTRAP_ADMIN_PASSWORD} -lt 12 ]]; then
  echo "BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters when set."
  exit 1
fi
if [[ ${#SECRET_KEY} -lt 32 ]]; then
  echo "SECRET_KEY must contain at least 32 characters."
  exit 1
fi
if [[ "${PUBLIC_HOST}" == *"://"* || "${PUBLIC_HOST}" == */* ]]; then
  echo "PUBLIC_HOST must be a hostname without scheme or path."
  exit 1
fi
if [[ ",${CORS_ORIGINS}," != *",https://${PUBLIC_HOST},"* ]]; then
  echo "CORS_ORIGINS must include https://${PUBLIC_HOST}."
  exit 1
fi
if [[ "${APP_DEBUG:-}" != "false" ||
      "${ENABLE_API_DOCS:-}" != "false" ||
      "${ALLOW_PUBLIC_REGISTRATION:-}" != "false" ]]; then
  echo "Production requires APP_DEBUG=false, ENABLE_API_DOCS=false, and ALLOW_PUBLIC_REGISTRATION=false."
  exit 1
fi

sudo install -d -m 0750 "${DATA_DIR}/mysql"
sudo install -d -m 0750 -o 10001 -g 10001 "${DATA_DIR}/audio"
sudo install -d -m 0750 -o 10001 -g 10001 "${DATA_DIR}/exports"
sudo install -d -m 0700 "${BACKUP_DIR}"
chmod 0600 "${ENV_FILE}"

cd "${PROJECT_DIR}"
docker compose --env-file "${ENV_FILE}" config --quiet
docker compose --env-file "${ENV_FILE}" build
docker compose --env-file "${ENV_FILE}" up -d
docker compose --env-file "${ENV_FILE}" ps

docker compose --env-file "${ENV_FILE}" exec -T backend \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=5).read().decode())"

echo "Deployment started. Local entry: http://127.0.0.1:8080"
echo "Public host: https://${PUBLIC_HOST}"
