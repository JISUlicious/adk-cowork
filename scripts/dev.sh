#!/usr/bin/env bash
# One-command dev loop: cowork-server + cowork-web Vite in parallel.
#
# Assumes COWORK_PORT + COWORK_TOKEN are set in the repo-root .env
# (see .env.sample). Both processes read them from there, so the
# Vite proxy and the FastAPI server line up automatically.
#
# Usage (from repo root or anywhere; script cd's to repo root):
#   scripts/dev.sh
#
# Ctrl+C stops both. Windows users: run the two commands in separate
# terminals — cd packages/cowork-web && npm run dev,
# and uv run python -m cowork_server — bash scripts don't work on cmd.

set -u
cd "$(dirname "$0")/.."

cleanup() {
  echo
  echo "[dev] stopping…"
  for pid in $(jobs -p); do
    kill "$pid" 2>/dev/null || true
  done
  # Give children a moment to shut down, then reap them.
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- sanity check: did the user wire .env? ---
if [[ -f ".env" ]] && ! grep -qE "^COWORK_PORT=" .env; then
  echo "[dev] warning: COWORK_PORT is not set in .env — the server"
  echo "[dev]          will pick a random port and Vite's proxy"
  echo "[dev]          will default to 9100. Set COWORK_PORT=9100"
  echo "[dev]          in .env to avoid connection-refused errors."
fi

echo "[dev] starting cowork-server…"
uv run python -m cowork_server &

echo "[dev] starting cowork-web (Vite)…"
(cd packages/cowork-web && npm run dev) &

# Block until one exits or the user Ctrl+C's. The EXIT trap cleans up
# the other child either way.
wait
