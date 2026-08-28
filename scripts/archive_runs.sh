#!/usr/bin/env bash
#
# Archive runs/ to a timestamped tarball.
#
# runs/ is gitignored, so the provenance record for every experiment lives
# outside version control and is lost with the machine unless it is copied
# somewhere else. This does the copying.
#
# Usage:
#   RUNS_BACKUP_DIR=~/Dropbox/msc-backups ./scripts/archive_runs.sh

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runs_dir="${repo_root}/runs"

if [ -z "${RUNS_BACKUP_DIR:-}" ]; then
  cat >&2 <<'MSG'
RUNS_BACKUP_DIR is not set, so there is nowhere to archive to.

Set it to a directory outside this repository — ideally one that is itself
backed up or synced — and run again:

    RUNS_BACKUP_DIR=~/Dropbox/msc-backups ./scripts/archive_runs.sh

Nothing has been written.
MSG
  exit 1
fi

if [ ! -d "$runs_dir" ]; then
  echo "No runs/ directory at ${runs_dir}; nothing to archive." >&2
  exit 1
fi

if [ -z "$(ls -A "$runs_dir" 2>/dev/null)" ]; then
  echo "runs/ is empty; nothing to archive." >&2
  exit 1
fi

mkdir -p "$RUNS_BACKUP_DIR"

stamp="$(date -u +%Y%m%d-%H%M%S)"
archive="${RUNS_BACKUP_DIR}/runs-${stamp}.tar.gz"

if [ -e "$archive" ]; then
  echo "Refusing to overwrite existing archive: ${archive}" >&2
  exit 1
fi

tar czf "$archive" -C "$repo_root" runs

run_count="$(find "$runs_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
size="$(du -h "$archive" | cut -f1 | tr -d ' ')"

echo "Archived ${run_count} run(s) to ${archive} (${size})"
