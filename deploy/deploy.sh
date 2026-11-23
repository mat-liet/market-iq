#!/usr/bin/env bash
# Deploy a commit from origin/main, and roll back if the app doesn't come up healthy.
#
# The GitHub Actions deploy job runs this through a forced SSH command (see
# docs/deployment.md), so the CI key can do nothing else. The commit to deploy
# arrives in $SSH_ORIGINAL_COMMAND. By hand: ./deploy/deploy.sh [<commit-sha>]
#
# Output goes to the public Actions log, so this never prints application logs.
#
# Everything runs inside main(), which bash has parsed in full before `git reset`
# replaces this file on disk.
set -euo pipefail

compose() { docker compose -f docker-compose.prod.yml "$@"; }

wait_healthy() {
  # "healthy" from the app's healthcheck; releases that predate the healthcheck
  # report their plain container state, where "running" is the best signal.
  local status
  for _ in $(seq 1 40); do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$(compose ps -q app)" 2>/dev/null || true)
    case "$status" in healthy|running) return 0 ;; esac
    sleep 3
  done
  return 1
}

main() {
  cd "$(dirname "$0")/.."
  local target="${SSH_ORIGINAL_COMMAND:-${1:-}}"

  git fetch --quiet origin main
  [ -n "$target" ] || target=$(git rev-parse origin/main)
  if ! [[ "$target" =~ ^[0-9a-f]{40}$ ]]; then
    echo "refusing: expected a full commit SHA" >&2
    exit 2
  fi
  if ! git merge-base --is-ancestor "$target" origin/main 2>/dev/null; then
    echo "refusing: $target is not on origin/main" >&2
    exit 2
  fi

  local previous
  previous=$(git rev-parse HEAD)
  # Over SSH (CI), only move forward: a leaked key must not be able to roll the
  # server back to an older release. Deliberate rollbacks are run by hand.
  if [ -n "${SSH_ORIGINAL_COMMAND:-}" ] && ! git merge-base --is-ancestor "$previous" "$target"; then
    echo "refusing: $target is older than the running $previous (roll back by hand)" >&2
    exit 2
  fi
  echo "deploying $target (running: $previous)"
  # Untracked files (.env, config/*.json, backups/) are left alone.
  git reset --hard --quiet "$target"

  if compose up -d --build --remove-orphans && wait_healthy; then
    docker image prune -f >/dev/null
    echo "deployed $target"
    exit 0
  fi

  echo "new version unhealthy; rolling back to $previous" >&2
  echo "inspect on the server: docker compose -f docker-compose.prod.yml logs app" >&2
  git reset --hard --quiet "$previous"
  if compose up -d --build --remove-orphans && wait_healthy; then
    echo "rolled back to $previous" >&2
  else
    echo "rollback is unhealthy too: needs attention on the server" >&2
  fi
  exit 1
}

main "$@"; exit
