"""One-off: run the (now transition-capturing) board sync for every board, so
status_transitions catches up to today. Mirrors POST /api/snapshot-all."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.projects import get_registry, resolve_cfg
from app.database import get_engine
from app.sync import sync_and_snapshot

for entry in get_registry():
    cfg = resolve_cfg(entry.key)
    _, maker = get_engine(entry.key, entry.db_file)
    db = maker()
    t0 = time.time()
    try:
        res = sync_and_snapshot(db, cfg, snapshot_date=None, force=True)
        print(f"[{entry.key}] OK snapshot={res['snapshot_date']} issues={res['issues']} "
              f"({time.time()-t0:.0f}s)", flush=True)
    except Exception as exc:
        print(f"[{entry.key}] ERROR {type(exc).__name__}: {exc}", flush=True)
    finally:
        db.close()
print("DONE", flush=True)
