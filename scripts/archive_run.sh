#!/usr/bin/env bash
# Commit a completed run archive without modifying files while Git is rebasing.
set -Eeuo pipefail

: "${RUN_DIR:?RUN_DIR is required}"
: "${GITHUB_REF_NAME:?GITHUB_REF_NAME is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
BRANCH="$GITHUB_REF_NAME"
LOG_TMP="${RUNNER_TEMP:-/tmp}/ddg-writeback-${GITHUB_RUN_ID}.log"
mkdir -p "$(dirname "$RUN_DIR")"
: > "$LOG_TMP"
exec > >(tee -a "$LOG_TMP") 2>&1

copy_failure_log() {
  local status=$?
  echo "Write-back failed with exit code ${status}." >> "$LOG_TMP"
  mkdir -p "$RUN_DIR"
  cp "$LOG_TMP" "$RUN_DIR/repository_writeback.log" || true
  exit "$status"
}
trap copy_failure_log ERR
trap 'cp "$LOG_TMP" "$RUN_DIR/repository_writeback.log" 2>/dev/null || true' EXIT

sync_branch() {
  git fetch origin "$BRANCH"
  git rebase "origin/$BRANCH"
}

push_with_retry() {
  local attempt
  for attempt in 1 2 3; do
    echo "Push attempt ${attempt}/3 to ${BRANCH}."
    if git push origin "HEAD:${BRANCH}"; then
      return 0
    fi
    if [[ "$attempt" -lt 3 ]]; then
      echo "Push rejected or raced; fetching and rebasing before retry."
      sync_branch
    fi
  done
  echo "Push failed after three attempts."
  return 1
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

echo "Synchronizing branch before staging run files."
sync_branch

git add "$RUN_DIR"
if git diff --cached --quiet; then
  echo "No run files changed; no archive commit required."
else
  git commit -m "chore(search): archive DuckDuckGo run ${GITHUB_RUN_ID}"
  push_with_retry
  echo "Primary run archive push succeeded."
fi

# Capture the write-back transcript in the run folder and commit it separately.
# The transcript is never appended to run.log while run.log is being committed.
echo "Preparing repository_writeback.log commit."
cp "$LOG_TMP" "$RUN_DIR/repository_writeback.log"
git add "$RUN_DIR/repository_writeback.log"
if ! git diff --cached --quiet; then
  git commit -m "chore(search): add writeback log for run ${GITHUB_RUN_ID}"
  echo "Pushing repository write-back log commit."
  push_with_retry
fi
trap - ERR
echo "Repository write-back completed."
