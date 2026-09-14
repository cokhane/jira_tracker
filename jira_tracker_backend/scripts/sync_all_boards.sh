#!/bin/bash
# Nightly all-boards Jira sync + snapshot — the launchd driver for POST /api/snapshot-all.
#
# Calls snapshot_all() in-process rather than over HTTP, so the job does not depend on the
# API server being up. Boards are pulled in parallel and per-board failures are isolated
# (see _run_for_all_boards in app/main.py), so one board erroring never stops the other.
#
# snapshot_all (NOT sync_all) is the entrypoint on purpose: sync_all only upserts `issues`,
# while every dashboard that shows a day — the Velocity Board above all — reads
# `daily_snapshots`. A nightly job that only synced would refresh the issue rows and leave
# the board frozen on the last day someone happened to press the button by hand.
# snapshot_all runs sync_and_snapshot, which syncs AND captures the day (app/sync.py).
#
# Safe to run by hand at any time: the sync is an idempotent upsert keyed by issue key and
# the snapshot replaces that day's rows.
#
# Designed for launchd, which supplies almost no environment: every path is absolute and
# the venv interpreter is called directly rather than activated. The working directory is
# set to the repo because Settings reads a RELATIVE ".env" (app/config.py) and the board
# registry a relative projects.yaml — from any other cwd the Jira token would be missing
# and the registry would come back empty.

set -euo pipefail

REPO="/Users/rhidzkhanahmad/Documents/axe/jira_tracker/jira_tracker_backend"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/.work/sync_all.log"

mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }

log "=== sync + snapshot all boards: start ==="
cd "$REPO"

# Both arguments are passed EXPLICITLY. These are FastAPI endpoints, so every parameter is
# annotated for request parsing; calling one as a plain Python function bypasses FastAPI and
# uses the signature defaults. Passing them here keeps this call independent of whatever
# those defaults happen to be. target=None means today, in the board's report timezone;
# force=False because overwriting a past day is a deliberate, human-confirmed act.
SYNC_JSON="$("$PY" -c '
import json
from app.main import snapshot_all
print(json.dumps(snapshot_all(target=None, force=False)))
')"

# Report every board, then exit non-zero if ANY of them failed — a silent partial sync
# should surface as a failed job, not as a clean run.
echo "$SYNC_JSON" | "$PY" -c '
import json, sys
boards = json.load(sys.stdin)["projects"]
for b in boards:
    bits = [f"{k}={b[k]}" for k in ("status", "snapshot_date", "issues", "error")
            if b.get(k) not in (None, "")]
    print("    %s: %s" % (b.get("key"), " ".join(bits)))
bad = [b for b in boards if b.get("status") != "success"]
if bad:
    sys.exit("    FAILED: %d of %d board(s) did not snapshot." % (len(bad), len(boards)))
'

log "=== sync + snapshot all boards: done ==="
