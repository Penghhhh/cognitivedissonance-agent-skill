"""Configuration loading, schema validation and hashing.

The config is JSON rather than YAML on purpose. Every reported number in this
skill is a function of (signals, config, index_version), so the config is a
research instrument, not a preference file: it has to parse identically on every
machine with no third-party YAML library present, and it has to be hashable so
that a run can be tied to the exact instrument that produced it. JSON gives both
for free; YAML gives neither without a dependency.

Sums are checked here rather than in the JSON Schema because "these weights must
sum to 1.0" is not expressible in the schema language, and an unchecked weight
vector silently rescales the index.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Imported by file path so the module works whether scripts/ is on sys.path or
# the file is executed directly.
try:  # pragma: no cover - trivial import shim
    from jsonschema_lite import ValidationError, validate
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from jsonschema_lite import ValidationError, validate  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
CONFIG_DIR = REPO_ROOT / "config"

_SUM_TOLERANCE = 1e-6


class ConfigError(Exception):
    """Raised when a config is structurally valid but semantically incoherent."""


def skill_version() -> str:
    version_file = REPO_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0-dev"


def read_text(path: str | Path) -> str:
    """Read UTF-8 text, tolerating a byte-order mark.

    Windows editors, PowerShell's ``Set-Content -Encoding UTF8`` and several
    spreadsheet exports all prepend a BOM. Rejecting those files with a raw
    ``Unexpected UTF-8 BOM`` from the JSON parser is a hostile failure for a
    research tool that expects hand-edited config and data files, and
    ``utf-8-sig`` decodes BOM-less files identically.
    """
    return Path(path).read_text(encoding="utf-8-sig")


def write_text(path: str | Path, text: str) -> None:
    """Write UTF-8 text with LF line endings on every platform.

    ``Path.write_text`` opens in text mode with universal-newline translation, so
    on Windows it silently rewrites every ``\\n`` as ``\\r\\n``. That makes a run on
    Windows produce byte-different artefacts from the identical run on Linux — the
    log, the state file and the generated reports all diverge — which for an
    artifact whose entire claim is reproducibility is a defect and not a
    cosmetic detail. ``newline="\\n"`` means "translate nothing".

    Uses ``utf-8`` rather than ``utf-8-sig`` on purpose: a BOM is accepted on read
    but never emitted on write, so the repository cannot accumulate them.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def open_text(path: str | Path, mode: str = "a"):
    """Open a UTF-8 text handle that never translates line endings.

    Used for the append-only JSONL log: a log written on Windows must be
    byte-identical to one written on Linux for the same inputs.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.open(mode, encoding="utf-8", newline="\n")


def load_schema(name: str) -> dict[str, Any]:
    """Load a schema from ``schemas/`` by file stem or file name."""
    filename = name if name.endswith(".json") else f"{name}.schema.json"
    path = SCHEMA_DIR / filename
    if not path.exists():
        raise ConfigError(f"schema not found: {path}")
    return json.loads(read_text(path))


def default_config_path() -> Path:
    return CONFIG_DIR / "cds.config.json"


def config_schema() -> dict[str, Any]:
    """The config's own schema, which lives beside the config rather than in schemas/.

    It is kept there so that ``"$schema": "./cds.config.schema.json"`` resolves for
    an editor opening the config file directly. Engine-output schemas live in
    ``schemas/`` and are reached through :func:`load_schema`.
    """
    return json.loads(read_text(CONFIG_DIR / "cds.config.schema.json"))


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load, schema-validate and semantic-check a config."""
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        raise ConfigError(f"config not found: {config_path}")
    try:
        config = json.loads(read_text(config_path))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {exc}") from exc

    schema = config_schema()
    errors = validate(schema, config)
    if errors:
        raise ValidationError([f"{config_path.name}: {e}" for e in errors])

    _check_semantics(config)
    return config


def _sum_of(mapping: dict[str, float]) -> float:
    return float(sum(mapping.values()))


def _check_semantics(config: dict[str, Any]) -> None:
    problems: list[str] = []

    def require_unit_sum(label: str, mapping: dict[str, float]) -> None:
        total = _sum_of(mapping)
        if abs(total - 1.0) > _SUM_TOLERANCE:
            problems.append(f"{label} must sum to 1.0, got {total:.6f}")

    require_unit_sum("index.weights", config["index"]["weights"])
    require_unit_sum("evaluator.evidence_weights", config["evaluator"]["evidence_weights"])
    require_unit_sum("evaluator.adjustment_cost_weights", config["evaluator"]["adjustment_cost_weights"])

    mixed = config["evaluator"].get("mixed")
    if mixed:
        require_unit_sum("evaluator.mixed.reduction_tendency_weights", mixed["reduction_tendency_weights"])

    thresholds = config["thresholds"]
    low, alert, high = thresholds["low"], thresholds["alert"], thresholds["high"]
    if not (low < alert < high):
        problems.append(f"thresholds must satisfy low < alert < high, got {low} / {alert} / {high}")

    # The dissonance gate is only meaningful if a gated conflict can never reach
    # an alert threshold. This is the single most important invariant in the
    # config: break it and a stance the agent never chose starts producing
    # "dissonance" cards, which is precisely the construct-validity failure the
    # gate exists to prevent.
    cap = config["index"]["gates"]["non_dissonant_cap"]
    floor = config["index"]["gates"]["volition_floor"]
    per_type = config.get("thresholds_by_type", {})
    effective_alerts = [alert, *per_type.values()]
    if cap >= min(effective_alerts):
        problems.append(
            "index.gates.non_dissonant_cap "
            f"({cap}) must be strictly below every alert threshold (min {min(effective_alerts)}); "
            "otherwise a non-dissonant conflict could be reported as dissonance"
        )
    if floor > 1.0 or floor < 0.0:
        problems.append(f"index.gates.volition_floor out of range: {floor}")

    for conflict_type, value in per_type.items():
        if value > high:
            problems.append(f"thresholds_by_type.{conflict_type} ({value}) exceeds thresholds.high ({high})")
        if value < low:
            problems.append(f"thresholds_by_type.{conflict_type} ({value}) is below thresholds.low ({low})")

    indeterminacy = config["channels"]["indeterminacy"]
    if indeterminacy["alert"] >= indeterminacy["high"]:
        problems.append(
            "channels.indeterminacy.alert must be below channels.indeterminacy.high, "
            f"got {indeterminacy['alert']} / {indeterminacy['high']}"
        )

    rules = config["evaluator"]["strategy_rules"]["rules"]
    ids = [rule["id"] for rule in rules]
    duplicates = sorted({rid for rid in ids if ids.count(rid) > 1})
    if duplicates:
        problems.append(f"strategy rule ids must be unique; duplicated: {duplicates}")

    if problems:
        raise ConfigError("config is incoherent:\n  - " + "\n  - ".join(problems))


def config_hash(config: dict[str, Any]) -> str:
    """Stable sha256 over the canonical serialisation of the config."""
    canonical = json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


# Public alias: the sensitivity and corpus harnesses need to re-check semantics
# after applying an override, without importing a private name.
check_semantics = _check_semantics


def canonical_hash(value: Any) -> str:
    """Stable sha256 over any JSON-serialisable value."""
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()
