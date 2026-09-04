#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
"""Archive T3 server trace logs before rotation discards them.

The T3 server keeps ten rotated 10 MB server.trace.ndjson files, which
covers only minutes of history under load. Each rotated file is copied once,
gzipped, into the archive, named by its first span's timestamp. The active
file is mirrored as current.ndjson so the newest spans are available too.
Archives older than KEEP_DAYS are deleted.

Runs from the t3-trace-archive.timer systemd user unit. Read the archive with
t3-profile-connects.py.
"""

import gzip
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

LOGS = Path.home() / ".t3" / "userdata" / "logs"
ARCHIVE = Path.home() / ".local" / "share" / "t3-trace-archive"
KEEP_DAYS = 30


def archive_name(path: Path) -> str:
    with path.open("rb") as f:
        first_line = f.readline()
    start_ns = int(json.loads(first_line)["startTimeUnixNano"])
    stamp = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(first_line).hexdigest()[:8]
    return f"trace-{stamp}-{digest}.ndjson.gz"


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archived = 0
    for rotated in LOGS.glob("server.trace.ndjson.*"):
        target = ARCHIVE / archive_name(rotated)
        if target.exists():
            continue
        tmp = target.with_suffix(".tmp")
        with rotated.open("rb") as src, gzip.open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp.replace(target)
        archived += 1

    active = LOGS / "server.trace.ndjson"
    current_tmp = ARCHIVE / "current.ndjson.tmp"
    shutil.copyfile(active, current_tmp)
    current_tmp.replace(ARCHIVE / "current.ndjson")

    cutoff = time.time() - KEEP_DAYS * 86400
    pruned = 0
    for old in ARCHIVE.glob("trace-*.ndjson.gz"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            pruned += 1
    print(f"archived {archived} rotated files, pruned {pruned}")


if __name__ == "__main__":
    main()
