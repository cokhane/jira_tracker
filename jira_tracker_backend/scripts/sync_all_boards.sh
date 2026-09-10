#!/bin/bash
# Nightly all-boards Jira sync — the launchd driver for POST /api/sync-all.
#
# Calls sync_all() in-process rather than over HTTP, so the job does not depend on the
# API server being up. Boards are pulled in parallel and per-board failures are isolated
# (see _run_for_all_boards in app/main.py), so one board erroring never stops the other.
#
# Safe to run by hand at any time: a sync is an idempotent upsert keyed by issue key.
#
# Designed for launchd, which supplies almost no environment: every path is absolute and
# the venv interpreter is called directly rather than activated. The working directory is
# set to the repo because Settings reads a RELATIVE ".env" (app/config.py) and the board
# registry a relative projects.yaml — from any other cwd the Jira token would be missing
# and the registry would come back empty.

set -euo pipefail

REPO="/Users/axeeeeee/anervea/jira_tracker/version_2/jira_tracker_backend"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/.work/sync_all.log"

mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }

log "=== sync all boards: start ==="
cd "$REPO"

# full=True mirrors the endpoint's own default: a complete pull rather than "changed since
# the last sync", so each nightly run self-heals anything an incremental pass would miss.
SYNC_JSON="$("$PY" -c '
import json
from app.main import sync_all
print(json.dumps(sync_all(full=True)))
')"

# Report every board, then exit non-zero if ANY of them failed — a silent partial sync
# should surface as a failed job, not as a clean run.
echo "$SYNC_JSON" | "$PY" -c '
import json, sys
boards = json.load(sys.stdin)["projects"]
for b in boards:
    bits = [f"{k}={b[k]}" for k in ("status", "fetched", "created", "updated", "error")
            if b.get(k) not in (None, "")]
    print("    %s: %s" % (b.get("key"), " ".join(bits)))
bad = [b for b in boards if b.get("status") != "success"]
if bad:
    sys.exit("    FAILED: %d of %d board(s) did not sync." % (len(bad), len(boards)))
'

log "=== sync all boards: done ==="
