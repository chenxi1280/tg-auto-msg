#!/usr/bin/env bash

set -euo pipefail

USER_NAME="${USER_NAME:-root}"
HOST="${HOST:-}"
BASE_DIR="${BASE_DIR:-/data/tgmsg}"
REF_NAME="${REF_NAME:-HEAD}"
ALLOW_DIRTY="${ALLOW_DIRTY:-0}"
KEEP_ARCHIVE="${KEEP_ARCHIVE:-0}"
EXPECTED_BRANCHES="${EXPECTED_BRANCHES:-release main master}"
CONFIRM_PRODUCTION_DEPLOY="${CONFIRM_PRODUCTION_DEPLOY:-0}"
SSH_OPTS=()

usage() {
  cat <<'EOF'
Usage:
  bash deploy/release.sh --host <host> [options]

Options:
  --host HOST           Target host, required
  --user USER           SSH user, default root
  --base-dir DIR        Remote base directory, default /data/tgmsg
  --ref REF             Git ref to release, default HEAD
  --allow-dirty         Allow releasing with local uncommitted changes
  --confirm-production-deploy
                        Confirm emergency local deploy to production
  --branch-list "..."   Allowed release branches, default "release main master"
  --ssh-opt OPT         Extra ssh/scp option, can be repeated
  -h, --help            Show this help

Examples:
  bash deploy/release.sh --host 47.250.167.174
  bash deploy/release.sh --host 47.250.167.174 --branch-list "release"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --user)
      USER_NAME="$2"
      shift 2
      ;;
    --base-dir)
      BASE_DIR="$2"
      shift 2
      ;;
    --ref)
      REF_NAME="$2"
      shift 2
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    --confirm-production-deploy)
      CONFIRM_PRODUCTION_DEPLOY=1
      shift
      ;;
    --branch-list)
      EXPECTED_BRANCHES="$2"
      shift 2
      ;;
    --ssh-opt)
      SSH_OPTS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing command: $cmd" >&2
    exit 1
  fi
}

if [[ -z "$HOST" ]]; then
  usage >&2
  exit 1
fi

require_command git
require_command ssh
require_command scp
require_command mktemp

is_production_target() {
  case "$HOST" in
    production-server|47.250.167.174)
      return 0
      ;;
  esac

  if [[ "$BASE_DIR" == "/data/tgmsg" ]]; then
    return 0
  fi
  return 1
}

is_github_actions() {
  [[ "${GITHUB_ACTIONS:-}" == "true" ]]
}

if is_production_target && ! is_github_actions; then
  cat >&2 <<EOF
WARNING: You are targeting the production environment.

Production deploys should go through GitHub Actions first.
Local direct deploys are reserved for emergency fixes only.
If you continue locally, you must backfill the same change into Git
before the next official Actions release, or production will drift again.
EOF
  if [[ "$CONFIRM_PRODUCTION_DEPLOY" != "1" ]]; then
    cat >&2 <<EOF

Refusing to continue without explicit confirmation.
Rerun with:
  bash deploy/release.sh ... --confirm-production-deploy
EOF
    exit 1
  fi
  echo "==> Emergency production deploy confirmed from local environment" >&2
fi

current_branch="$(git branch --show-current)"
if [[ -z "$current_branch" ]]; then
  echo "Cannot detect current git branch" >&2
  exit 1
fi

branch_allowed=0
for branch in $EXPECTED_BRANCHES; do
  if [[ "$current_branch" == "$branch" ]]; then
    branch_allowed=1
    break
  fi
done

if [[ "$branch_allowed" != "1" ]]; then
  echo "Refusing to release from branch '${current_branch}'. Allowed branches: ${EXPECTED_BRANCHES}" >&2
  exit 1
fi

if [[ "$current_branch" == "master" ]]; then
  echo "Warning: releasing from legacy branch 'master'. Migrate to 'main' when possible." >&2
fi

if [[ "$ALLOW_DIRTY" != "1" ]] && [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit or stash changes first, or rerun with --allow-dirty." >&2
  exit 1
fi

short_sha="$(git rev-parse --short "$REF_NAME")"
release_id="$(date '+%Y%m%d%H%M%S')_${short_sha}"
archive_path="$(mktemp "/tmp/tgmsg-release-${release_id}.XXXXXX.tar.gz")"
remote_archive="${BASE_DIR}/incoming/${release_id}.tar.gz"
remote_release_dir="${BASE_DIR}/releases/${release_id}"

trap '[[ "$KEEP_ARCHIVE" == "1" ]] || rm -f "$archive_path"' EXIT

echo "==> Creating release archive for ${REF_NAME} (${short_sha})"
git archive --format=tar.gz --output "$archive_path" "$REF_NAME"

echo "==> Uploading release archive to ${USER_NAME}@${HOST}:${remote_archive}"
ssh "${SSH_OPTS[@]}" "${USER_NAME}@${HOST}" "mkdir -p '${BASE_DIR}/incoming' '${BASE_DIR}/releases'"
scp "${SSH_OPTS[@]}" "$archive_path" "${USER_NAME}@${HOST}:${remote_archive}"

echo "==> Installing release ${release_id} on ${HOST}"
ssh "${SSH_OPTS[@]}" "${USER_NAME}@${HOST}" "\
set -euo pipefail && \
rm -rf '${remote_release_dir}' && \
mkdir -p '${remote_release_dir}' && \
tar -xzf '${remote_archive}' -C '${remote_release_dir}' && \
bash '${remote_release_dir}/deploy/server-install-release.sh' \
  --base-dir '${BASE_DIR}' \
  --release-dir '${remote_release_dir}' \
  --release-id '${release_id}' && \
rm -f '${remote_archive}'"

echo "✅ Release ${release_id} completed"
