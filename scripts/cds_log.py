"""JSONL audit logging.

Every stage appends one record. The envelope carries the identifiers needed to
reconstruct a run without the console transcript, because the v0.1 risk table
promised reproducibility while its log format stored only "run id, input summary,
score, decision, output" - none of which ties a result to the model, the decoding
settings or the exact instrument version that produced it.

``record_id`` is deterministic over content, so replaying the same inputs in a
later session yields the same ids. That is what lets the test suite assert
cross-run identity instead of settling for "similar".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cds_config import REPO_ROOT, canonical_hash, open_text, skill_version

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


def make_run_id(prefix: str = "cds") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{os.urandom(2).hex()}"


def resolve_log_path(config: dict[str, Any], override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    configured = Path(config["logging"]["path"])
    return configured if configured.is_absolute() else REPO_ROOT / configured


def build_record(
    *,
    config: dict[str, Any],
    run_id: str,
    turn_id: int,
    stage: str,
    payload: dict[str, Any],
    event_id: str | None = None,
    signals: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Assemble one log envelope."""
    signals_hash = canonical_hash(signals) if signals is not None else None
    config_digest = canonical_hash(config)
    digest_source = {
        # The instrument is part of the observation: two runs whose only
        # difference is the config are different observations and must not share
        # a record id.
        "skill_version": skill_version(),
        "index_version": config["index"]["index_version"],
        "config_hash": config_digest,
        "run_id": run_id,
        "turn_id": turn_id,
        "stage": stage,
        "event_id": event_id,
        "signals_hash": signals_hash,
        "payload": payload,
    }
    return {
        "schema_version": skill_version(),
        "skill_version": skill_version(),
        "index_version": config["index"]["index_version"],
        "config_hash": config_digest,
        "record_id": "cds_rec_" + canonical_hash(digest_source).split(":", 1)[1][:12],
        "run_id": run_id,
        "turn_id": turn_id,
        "stage": stage,
        "ts": timestamp or utc_now(),
        "event_id": event_id,
        "signals_hash": signals_hash,
        "model": model,
        "payload": payload,
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    # open_text pins LF, so a log written on Windows is byte-identical to one
    # written on Linux for the same inputs.
    with open_text(path, "a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_records(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    records = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
