# /// script
# requires-python = ">=3.11"
# ///
"""Copy one project's live threads from one T3 database into another.

Usage: t3-transplant-threads.py <source.sqlite> <source-root> <target.sqlite> <target-root>

<source.sqlite> is a snapshot (`VACUUM INTO`) of the source server's state.sqlite.
<target.sqlite> is the target server's state.sqlite, and that server must be
stopped. The target project (workspace root <target-root>) must already exist.

The thread events are appended to the target's event store with the project id
and workspace root rewritten; the target server projects them when it next
starts, because projection bootstrap replays events past each projector's
cursor. Provider resume cursors and checkpoint diff blobs come along. The
target is backed up next to itself before any write.

Not copied, so the caller moves them: attachment files (ids are printed),
checkpoint refs (`git fetch <source-repo> 'refs/t3/*:refs/t3/*'`), and provider
transcripts (Claude project dirs, Codex rollouts).
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def json_fragment(text: str) -> str:
    """`text` as it appears inside a JSON string literal."""
    return json.dumps(text)[1:-1]


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    source_path, source_root, target_path, target_root = sys.argv[1:]
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)

    def project_id(db: sqlite3.Connection, root: str, which: str) -> str:
        rows = db.execute(
            "SELECT project_id FROM projection_projects WHERE workspace_root = ? AND deleted_at IS NULL",
            (root,),
        ).fetchall()
        if len(rows) != 1:
            raise SystemExit(f"Expected one live {which} project at {root}, found {len(rows)}")
        return rows[0][0]

    source_project = project_id(source, source_root, "source")
    target_project = project_id(target, target_root, "target")
    threads = [row[0] for row in source.execute(
        "SELECT thread_id FROM projection_threads WHERE project_id = ? AND deleted_at IS NULL ORDER BY created_at",
        (source_project,),
    )]
    if not threads:
        raise SystemExit(f"No live threads in the source project at {source_root}")
    marks = ",".join("?" * len(threads))
    clashes = target.execute(
        f"SELECT DISTINCT stream_id FROM orchestration_events WHERE aggregate_kind = 'thread' AND stream_id IN ({marks})",
        threads,
    ).fetchall()
    if clashes:
        raise SystemExit(f"Target already has events for {len(clashes)} of these threads, e.g. {clashes[0][0]}")

    replacements = [
        (source_project, target_project),
        (json_fragment(source_root), json_fragment(target_root)),
    ]

    def rewrite(text: str | None) -> str | None:
        if text is None:
            return None
        for old, new in replacements:
            text = text.replace(old, new)
        return text

    events = source.execute(
        f"""SELECT event_id, aggregate_kind, stream_id, stream_version, event_type, occurred_at, command_id,
                   causation_event_id, correlation_id, actor_kind, payload_json, metadata_json
            FROM orchestration_events WHERE aggregate_kind = 'thread' AND stream_id IN ({marks}) ORDER BY sequence""",
        threads,
    ).fetchall()
    runtimes = source.execute(
        f"""SELECT thread_id, provider_name, adapter_key, runtime_mode, last_seen_at, resume_cursor_json,
                   runtime_payload_json, provider_instance_id
            FROM provider_session_runtime WHERE thread_id IN ({marks})""",
        threads,
    ).fetchall()
    diffs = source.execute(
        f"SELECT thread_id, from_turn_count, to_turn_count, diff, created_at FROM checkpoint_diff_blobs WHERE thread_id IN ({marks})",
        threads,
    ).fetchall()

    backup = Path(f"{target_path}.bak-{datetime.now():%Y%m%dT%H%M%S}")
    target.execute("VACUUM INTO ?", (str(backup),))
    with target:
        target.executemany(
            """INSERT INTO orchestration_events (event_id, aggregate_kind, stream_id, stream_version, event_type,
                   occurred_at, command_id, causation_event_id, correlation_id, actor_kind, payload_json, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(*event[:10], rewrite(event[10]), rewrite(event[11])) for event in events],
        )
        target.executemany(
            """INSERT OR IGNORE INTO provider_session_runtime (thread_id, provider_name, adapter_key, runtime_mode,
                   status, last_seen_at, resume_cursor_json, runtime_payload_json, provider_instance_id)
               VALUES (?, ?, ?, ?, 'stopped', ?, ?, ?, ?)""",
            [(*runtime[:5], runtime[5], rewrite(runtime[6]), runtime[7]) for runtime in runtimes],
        )
        target.executemany(
            "INSERT OR IGNORE INTO checkpoint_diff_blobs (thread_id, from_turn_count, to_turn_count, diff, created_at) VALUES (?, ?, ?, ?, ?)",
            diffs,
        )

    attachments = sorted({
        attachment["id"]
        for (payload,) in source.execute(
            f"SELECT payload_json FROM orchestration_events WHERE event_type = 'thread.message-sent' AND stream_id IN ({marks})",
            threads,
        )
        for attachment in (json.loads(payload).get("attachments") or [])
    })
    print(f"backup: {backup}")
    print(f"copied {len(threads)} threads, {len(events)} events, {len(runtimes)} resume cursors, {len(diffs)} diff blobs")
    print("attachment ids to copy:", *attachments, sep="\n  ")


if __name__ == "__main__":
    main()
