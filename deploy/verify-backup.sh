#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/backup-directory"
  exit 1
fi

backup_dir="$(realpath "$1")"
if [[ ! -d "${backup_dir}" ]]; then
  echo "Backup directory does not exist: ${backup_dir}"
  exit 1
fi

for required in database.sql audio-exports.tar.gz SHA256SUMS; do
  if [[ ! -s "${backup_dir}/${required}" ]]; then
    echo "Missing or empty backup file: ${required}"
    exit 1
  fi
done

(
  cd "${backup_dir}"
  sha256sum --check SHA256SUMS
  tar -tzf audio-exports.tar.gz >/dev/null
)

if ! grep -qE '^(CREATE TABLE|INSERT INTO|-- MySQL dump)' \
  "${backup_dir}/database.sql"; then
  echo "database.sql does not look like a MySQL dump."
  exit 1
fi

echo "Backup verification passed: ${backup_dir}"
