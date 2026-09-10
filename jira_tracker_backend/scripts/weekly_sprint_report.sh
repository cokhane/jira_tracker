#!/bin/bash
# Weekly All-Boards sprint report — sync from Jira, then regenerate the Markdown report.
#
# Runs the full /create-md-report chain unattended:
#   1. sync + snapshot every configured board (NEX, STH) from Jira
#   2. Pass A — dump the deterministic per-board compare data
#   3. Claude authors the narrative JSONs, then Pass B builds the combined report
#   4. verify the Overview table reconciles
#
# Safe to run by hand at any time. Snapshots are idempotent per day, so a second run
# on the same day replaces that day's snapshot rather than duplicating it.
#
# Designed for launchd, which supplies almost no environment: every path is absolute
# and the venv interpreter is called directly rather than activated.

set -euo pipefail

REPO="/Users/axeeeeee/anervea/jira_tracker/version_2/jira_tracker_backend"
PY="$REPO/.venv/bin/python"
OUT_DIR="$HOME/Documents/sprint_report"
LOG="$OUT_DIR/.work/weekly_report.log"
CLAUDE="/opt/homebrew/bin/claude"

mkdir -p "$OUT_DIR/.work"
exec >> "$LOG" 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "=== weekly sprint report: start ==="
cd "$REPO"

# --- Step 1: sync + snapshot every board -------------------------------------
# snapshot_all() isolates per-board failures, so one board erroring never aborts the
# other. We still abort the report if ANY board failed: a partial sync would silently
# produce a report built on stale data for that board.
log "step 1/4 — sync + snapshot all boards from Jira (full pull, several minutes)"
SYNC_JSON="$("$PY" -c '
import json
from app.main import snapshot_all
print(json.dumps(snapshot_all(target=None, force=False)))
')"
echo "$SYNC_JSON" | "$PY" -c '
import json, sys
boards = json.load(sys.stdin)["projects"]
bad = [b for b in boards if b.get("status") != "success"]
for b in boards:
    fields = [b.get("key"), b.get("status"), b.get("snapshot_date"),
              b.get("issues"), b.get("error")]
    print("    " + " ".join(str(f) for f in fields if f not in (None, "")))
if bad:
    sys.exit("    ABORT: %d board(s) failed to sync - refusing to build a stale report."
             % len(bad))
'

# --- Step 2: Pass A ----------------------------------------------------------
log "step 2/4 — Pass A: dump per-board compare data"
"$PY" scripts/generate_compare_decks.py --pass a

# --- Step 3: narratives + Pass B --------------------------------------------
# Claude authors only the prose (achievements + roadblocks); every number in the
# report is computed by Pass B from the tracker DBs.
log "step 3/4 — Claude authors narratives, then Pass B builds the report"
"$CLAUDE" -p \
  --permission-mode acceptEdits \
  --allowedTools "Read Write Bash" \
  --add-dir "$OUT_DIR" \
  "You are running unattended as a scheduled job. Follow the create-md-report skill's
Step 2 and Step 3 exactly, and do not ask any questions.

Working dir is $REPO. The work dir is $OUT_DIR/.work/.

1. Read $OUT_DIR/.work/NEX_compare.md and $OUT_DIR/.work/STH_compare.md.
2. For EACH board (NEX, STH), write $OUT_DIR/.work/<KEY>_narrative.json with this schema:
   {\"achievements\": [5-7 full-sentence bullets], \"roadblocks\": [3 cards with id
   (R01/R02/R03), concern, impact, mitigation, help_needed]}
   Ground achievements STRICTLY in that board's completed ticket titles — group related
   tickets into a theme and name the outcome, never the ticket id. Ground roadblocks in
   the blocked ticket titles; if a board has no blocked tickets, infer risks from
   carry-over volume, completion rate and delivery concentration. Never invent a ticket
   or a number.
3. Run: $PY scripts/generate_compare_decks.py --pass b
4. Verify the generated report: each board shows non-zero Shipped and Committed, the
   Team Load & Delivery tables are populated, and Committed == Carry-over + New on every
   Overview row including the Total. Print the report path and the Overview table.

Report what you did in under 10 lines."

# --- Step 4: verify the artifact exists -------------------------------------
log "step 4/4 — verify output"
REPORT="$OUT_DIR/AllBoards_Sprint_Report_$(date '+%Y-%m-%d').md"
if [[ ! -s "$REPORT" ]]; then
    log "FAILED: expected report not found at $REPORT"
    exit 1
fi
log "OK: $REPORT ($(wc -c < "$REPORT" | tr -d ' ') bytes)"
log "=== weekly sprint report: done ==="
