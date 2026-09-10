#!/usr/bin/env python3
"""CDS-Skill command line interface.

This is the deterministic half of the skill. The model perceives; this program
computes, decides, renders and records. Nothing here calls a model, opens a
network connection, or reads anything outside the paths it is given, so a
reviewer can reproduce every reported number from a stored signal packet.

Typical closed loop (ambient mode, one call)::

    python scripts/cds.py run --signals packet.json

Interactive loop, one station per call::

    python scripts/cds.py detect --signals packet.json
    python scripts/cds.py command 处理
    python scripts/cds.py evaluate --detection detection.json
    python scripts/cds.py respond --evaluation evaluation.json

Use ``--json`` for the raw structure, ``--card-only`` for just the cards to show
the user, and ``--no-log`` to suppress the JSONL record in throwaway experiments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python scripts/cds.py` from anywhere, and imports from the sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _stream in (sys.stdout, sys.stderr):
    try:  # Chinese cards on a cp936 Windows console would otherwise raise
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

from cds_cards import all_cards, detect_card, evaluation_card, response_card  # noqa: E402
from cds_config import (  # noqa: E402
    ConfigError,
    check_semantics,
    config_hash,
    config_schema,
    load_config,
    load_schema,
    read_text,
    skill_version,
    write_text,
)
from cds_evaluator import StageError, build_evaluation  # noqa: E402
from cds_index import build_detection  # noqa: E402
from cds_log import append_record, build_record, make_run_id, resolve_log_path  # noqa: E402
from cds_state import StateError, StateMachine  # noqa: E402
from jsonschema_lite import ValidationError, validate  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID_INPUT = 3
EXIT_STATE = 4


class CliError(Exception):
    """A user-facing failure with a defined exit code."""

    def __init__(self, message: str, code: int = EXIT_INVALID_INPUT) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# I/O helpers
# --------------------------------------------------------------------------


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise CliError(f"file not found: {target}")
    try:
        return json.loads(read_text(target))
    except json.JSONDecodeError as exc:
        raise CliError(f"{target} is not valid JSON: {exc}") from exc


def _write_json(path: str | Path | None, data: dict[str, Any]) -> None:
    if not path:
        return
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _emit(payload: dict[str, Any], args: argparse.Namespace, card: str | None = None) -> None:
    """Print either the structure, the card, or both, according to the flags."""
    if getattr(args, "card_only", False):
        print(card if card is not None else "")
        return
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if card:
        print(card)
        print()
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _validate_signals(packet: dict[str, Any]) -> None:
    errors = validate(load_schema("signals"), packet)
    if errors:
        raise CliError("signal packet failed schema validation:\n  - " + "\n  - ".join(errors))


def _validate_output(schema_name: str, payload: dict[str, Any]) -> None:
    """Assert the emitted structure against its published schema.

    Running this on every emit is deliberate: it is the only way the schemas stay
    true. The cost is a few milliseconds; the alternative is documentation that
    drifts from the code.
    """
    errors = validate(load_schema(schema_name), payload)
    if errors:
        raise CliError(
            f"internal error: emitted {schema_name} does not satisfy its own schema:\n  - "
            + "\n  - ".join(errors),
            code=EXIT_STATE,
        )


def _model_metadata(args: argparse.Namespace) -> dict[str, Any] | None:
    fields = {
        "provider": getattr(args, "provider", None),
        "name": getattr(args, "model", None),
        "version": getattr(args, "model_version", None),
        "temperature": getattr(args, "temperature", None),
        "seed": getattr(args, "seed", None),
    }
    return fields if any(value is not None for value in fields.values()) else None


def _apply_overrides(config: dict[str, Any], pairs: list[str] | None) -> dict[str, Any]:
    """Apply ``--set a.b.c=value`` overrides, then re-validate.

    Study 1 needs to sweep configurations (weights, thresholds, profile, arm) while
    changing nothing else. Overriding at load time rather than by editing files
    keeps the shipped config as the single source of truth and makes every variant
    hashable and loggable on the same terms as the base.

    The value is parsed as JSON, so ``--set thresholds.alert=0.5`` gives a number
    and ``--set skill.mode=placebo`` gives a string.

    Paths may create a leaf, not a branch: every *intermediate* segment must
    already exist, but the final key need not. That allows adding an entry to an
    open map such as ``thresholds_by_type``, and typos are still caught, because
    the patched config is re-validated and ``additionalProperties: false`` plus the
    ``propertyNames`` enums reject an unknown key. Validating the outcome is
    stricter than validating the path, so it is the check worth having.
    """
    if not pairs:
        return config
    patched = json.loads(json.dumps(config))  # deep copy
    for pair in pairs:
        if "=" not in pair:
            raise CliError(f"--set expects key=value, got {pair!r}", code=EXIT_USAGE)
        dotted, _, raw = pair.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw  # bare words are treated as strings
        node: Any = patched
        keys = dotted.split(".")
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node:
                raise CliError(f"--set path {dotted!r} does not exist in the config", code=EXIT_USAGE)
            node = node[key]
        if not isinstance(node, dict):
            raise CliError(f"--set path {dotted!r} does not point into an object", code=EXIT_USAGE)
        node[keys[-1]] = value

    errors = validate(config_schema(), patched)
    if errors:
        raise CliError("override produced an invalid config:\n  - " + "\n  - ".join(errors), code=EXIT_USAGE)
    try:
        check_semantics(patched)
    except ConfigError as exc:
        raise CliError(f"override produced an incoherent config: {exc}", code=EXIT_USAGE) from exc
    return patched


def _log_stage(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    run_id: str,
    turn_id: int,
    stage: str,
    payload: dict[str, Any],
    event_id: str | None = None,
    signals: dict[str, Any] | None = None,
) -> None:
    if getattr(args, "no_log", False) or not config["logging"]["enabled"]:
        return
    record = build_record(
        config=config,
        run_id=run_id,
        turn_id=turn_id,
        stage=stage,
        payload=payload,
        event_id=event_id,
        signals=signals if config["logging"]["include_signals"] else None,
        model=_model_metadata(args),
    )
    append_record(resolve_log_path(config, getattr(args, "log", None)), record)


def _machine(args: argparse.Namespace, config: dict[str, Any]) -> StateMachine:
    """Load the state file, or start a new run.

    ``run_id`` is deliberately left as ``None`` when the caller did not pass
    ``--run-id``: that tells :meth:`StateMachine.load` to continue whichever run
    the state file already holds.
    """
    return StateMachine.load(config, getattr(args, "run_id", None), getattr(args, "state", None))


def _bind_run(machine: StateMachine, args: argparse.Namespace, signals: dict[str, Any]) -> str:
    """Establish the run id and write it back into the packet.

    A stored run keeps its id, so every stage of one interactive loop lands in the
    same log partition. A fresh run prefers ``--run-id``, then the packet's own id.
    """
    if not machine.loaded:
        if getattr(args, "run_id", None):
            machine.data["run_id"] = args.run_id
        elif signals.get("run_id"):
            machine.data["run_id"] = signals["run_id"]
        else:
            machine.data["run_id"] = make_run_id()
    signals["run_id"] = machine.data["run_id"]
    return machine.data["run_id"]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_detect(args: argparse.Namespace, config: dict[str, Any]) -> int:
    signals = _read_json(args.signals)
    _validate_signals(signals)

    machine = _machine(args, config)
    _bind_run(machine, args, signals)
    if not args.no_turn_advance:
        machine.advance_turn()
    signals.setdefault("turn_id", machine.data["turn"])

    detection = build_detection(signals, config)
    transition = machine.ingest_detection(detection)
    detection["state"] = transition
    machine.save()

    card = detect_card(detection, config)
    _validate_output("detection", detection)
    _log_stage(
        args,
        config,
        run_id=signals["run_id"],
        turn_id=signals["turn_id"],
        stage="detect",
        payload=detection,
        event_id=detection["conflict_event"]["event_id"],
        signals=signals,
    )
    _write_json(args.out, detection)
    _emit(detection, args, card)
    return EXIT_OK


def cmd_evaluate(args: argparse.Namespace, config: dict[str, Any]) -> int:
    detection = _read_json(args.detection)
    signals = _read_json(args.signals) if args.signals else None
    if signals is None:
        raise CliError(
            "evaluate needs --signals: the detection record holds the index but not the "
            "rated evidence the evaluator must judge"
        )
    _validate_signals(signals)

    machine = _machine(args, config)
    if not machine.loaded:
        machine.data["run_id"] = detection.get("run_id") or machine.data["run_id"]
    if not args.force:
        if machine.path is None:
            print(
                "note: no --state given, so the EVALUATING precondition cannot be checked; "
                "pass --state to enforce the recorded loop",
                file=sys.stderr,
            )
        else:
            machine.begin_evaluation()

    evaluation = build_evaluation(detection, signals, config)
    evaluation["response_plan"]["transparency_card"] = evaluation_card(evaluation, config)
    _validate_output("evaluation", evaluation)

    machine.save()
    _log_stage(
        args,
        config,
        run_id=evaluation["run_id"],
        turn_id=evaluation["turn_id"],
        stage="evaluate",
        payload=evaluation,
        event_id=evaluation["event_id"],
        signals=signals,
    )
    _write_json(args.out, evaluation)
    _emit(evaluation, args, evaluation_card(evaluation, config))
    return EXIT_OK


def cmd_respond(args: argparse.Namespace, config: dict[str, Any]) -> int:
    evaluation = _read_json(args.evaluation)
    plan = evaluation["response_plan"]
    card = response_card(evaluation, config)

    machine = _machine(args, config)
    if not machine.loaded:
        machine.data["run_id"] = evaluation.get("run_id") or machine.data["run_id"]
    if machine.path is None:
        print(
            "note: no --state given, so the RESPONDING precondition cannot be checked; "
            "pass --state to enforce the recorded loop",
            file=sys.stderr,
        )
        completion = {
            "outcome": "resolved" if plan["stance_update"]["changed"] else "unresolved",
            "state": "MONITORING",
        }
    else:
        completion = machine.complete_response(
            stance_changed=plan["stance_update"]["changed"], strategy=plan["strategy"]
        )

    payload = {
        "run_id": evaluation.get("run_id"),
        "turn_id": evaluation.get("turn_id"),
        "event_id": evaluation.get("event_id"),
        "strategy": plan["strategy"],
        "branch": plan["branch"],
        "language_acts": plan["language_acts"],
        "stance_update": plan["stance_update"],
        "constraints": plan["constraints"],
        "outcome": completion["outcome"],
        "state": {"from": "RESPONDING", "to": completion["state"]},
    }
    _log_stage(
        args,
        config,
        run_id=evaluation.get("run_id"),
        turn_id=evaluation.get("turn_id") or 0,
        stage="respond",
        payload=payload,
        event_id=evaluation.get("event_id"),
    )
    _write_json(args.out, payload)
    _emit(payload, args, card)
    return EXIT_OK


def cmd_command(args: argparse.Namespace, config: dict[str, Any]) -> int:
    machine = _machine(args, config)
    machine.advance_turn()
    result = machine.handle_command(args.word)
    machine.save()
    _log_stage(
        args,
        config,
        run_id=machine.data["run_id"],
        turn_id=machine.data["turn"],
        stage="command",
        payload=result,
        event_id=result.get("event_id"),
    )
    _emit(result, args, result.get("message"))
    return EXIT_OK if result.get("accepted") else EXIT_OK


def cmd_status(args: argparse.Namespace, config: dict[str, Any]) -> int:
    machine = _machine(args, config)
    _emit(machine.status(), args)
    return EXIT_OK


def cmd_run(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """One-shot closed loop, valid only for ambient non-interactive arms."""
    if config["skill"]["interaction"] != "ambient":
        raise CliError(
            "run is the ambient one-shot loop; with interaction=interactive use "
            "detect / command / evaluate / respond so the user decision is recorded",
            code=EXIT_USAGE,
        )
    signals = _read_json(args.signals)
    _validate_signals(signals)
    if args.run_id:
        signals.setdefault("run_id", args.run_id)
    if signals.get("run_id") is None:
        signals["run_id"] = make_run_id()

    machine = _machine(args, config)
    _bind_run(machine, args, signals)
    if not args.no_turn_advance:
        machine.advance_turn()
    signals.setdefault("turn_id", machine.data["turn"])

    detection = build_detection(signals, config)
    transition = machine.ingest_detection(detection)
    detection["state"] = transition
    machine.save()
    _validate_output("detection", detection)

    evaluation = None
    cards = [detect_card(detection, config)]
    if detection["tension_result"]["next_action"] == "auto_evaluate":
        machine.begin_evaluation()
        evaluation = build_evaluation(detection, signals, config)
        cards.append(evaluation_card(evaluation, config))
        cards.append(response_card(evaluation, config))
        machine.complete_response(
            stance_changed=evaluation["response_plan"]["stance_update"]["changed"],
            strategy=evaluation["response_plan"]["strategy"],
        )
        machine.save()

    payload = {"detection": detection, "evaluation": evaluation, "state": machine.status()["state"]}
    if not args.no_log:
        _log_stage(
            args,
            config,
            run_id=signals["run_id"],
            turn_id=signals["turn_id"],
            stage="detect",
            payload=detection,
            event_id=detection["conflict_event"]["event_id"],
            signals=signals,
        )
        if evaluation is not None:
            _log_stage(
                args,
                config,
                run_id=signals["run_id"],
                turn_id=signals["turn_id"],
                stage="evaluate",
                payload=evaluation,
                event_id=evaluation["event_id"],
                signals=signals,
            )

    _write_json(args.out, payload)
    _emit(payload, args, "\n\n".join(cards))
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, config: dict[str, Any]) -> int:
    signals = _read_json(args.signals)
    _validate_signals(signals)
    print(f"OK  {args.signals} satisfies schemas/signals.schema.json")
    print(f"    config_hash {config_hash(config)}")
    return EXIT_OK


def cmd_config(args: argparse.Namespace, config: dict[str, Any]) -> int:
    summary = {
        "skill_version": skill_version(),
        "config_version": config["config_version"],
        "config_hash": config_hash(config),
        "index_version": config["index"]["index_version"],
        "mode": config["skill"]["mode"],
        "interaction": config["skill"]["interaction"],
        "profile": config["skill"]["profile"],
        "language": config["skill"]["language"],
        "numeric_cards": config["skill"]["numeric_cards"],
        "thresholds": config["thresholds"],
        "index_weights": config["index"]["weights"],
        "gates": config["index"]["gates"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_selftest(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Cheap invariant checks that must hold for any config."""
    failures: list[str] = []
    warnings: list[str] = []

    gates = config["index"]["gates"]
    alerts = [config["thresholds"]["alert"], *(config.get("thresholds_by_type") or {}).values()]
    if gates["non_dissonant_cap"] >= min(alerts):
        failures.append("the dissonance cap does not sit below every alert threshold")

    weights = config["index"]["weights"]
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        failures.append("index weights do not sum to 1")

    # A global knob that no conflict type actually reads is a trap: it looks
    # adjustable, does nothing, and quietly zeroes the threshold sweep.
    conflict_types = {"evidence_vs_stance", "evidence_vs_evidence", "user_hint_vs_stance", "memory_vs_current"}
    per_type = config.get("thresholds_by_type") or {}
    if conflict_types <= set(per_type):
        failures.append(
            "every conflict type has a per-type alert override, so thresholds.alert is inert; "
            "remove the redundant entries or the threshold sweep will report a false zero"
        )
    elif abs(per_type.get("evidence_vs_stance", -1) - config["thresholds"]["alert"]) < 1e-9:
        warnings.append("thresholds_by_type.evidence_vs_stance merely repeats thresholds.alert; remove it")

    for name in ("signals", "detection", "evaluation", "log_record"):
        try:
            load_schema(name)
        except Exception as exc:  # pragma: no cover - surfaces a packaging error
            failures.append(f"schema {name} did not load: {exc}")

    if failures:
        print("SELFTEST FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return EXIT_STATE
    for warning in warnings:
        print(f"warning: {warning}")
    print(f"selftest OK  (skill {skill_version()}, config_hash {config_hash(config)[:19]}...)")
    return EXIT_OK


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def _common_flags(suppress_defaults: bool) -> argparse.ArgumentParser:
    """Flags accepted both before and after the subcommand.

    The top-level parser carries real defaults; the subparser copies suppress
    theirs. Without that asymmetry the subparser's default would overwrite a value
    supplied before the subcommand, so ``cds.py --json run ...`` would silently
    lose ``--json``.
    """
    common = argparse.ArgumentParser(add_help=False)
    default = argparse.SUPPRESS if suppress_defaults else None

    def add(*names: str, **kwargs: Any) -> None:
        kwargs["default"] = default
        common.add_argument(*names, **kwargs)

    add("--config", help="path to cds.config.json (defaults to config/cds.config.json)")
    add("--set", action="append", dest="overrides", metavar="KEY=VALUE",
        help="override one config value, e.g. --set skill.profile=dissonance_reduction (repeatable)")
    add("--json", action="store_true", help="print the raw structure instead of the human card")
    add("--card-only", action="store_true", help="print only the transparency card")
    add("--no-log", action="store_true", help="do not append to the JSONL log")
    add("--log", help="override the log path")
    add("--state", help="path to the state file (omit for a stateless run)")
    add("--run-id", help="reuse a run id instead of minting one")
    add("--model", help="model name recorded in the log envelope")
    add("--provider", help="model provider recorded in the log envelope")
    add("--model-version", help="model version recorded in the log envelope")
    add("--temperature", type=float, help="decoding temperature recorded in the log envelope")
    add("--seed", type=int, help="random seed recorded in the log envelope")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_flags(suppress_defaults=True)
    parser = argparse.ArgumentParser(
        prog="cds.py",
        parents=[_common_flags(suppress_defaults=False)],
        description="CDS-Skill: deterministic detect / evaluate / respond engine for cognitive-dissonance-simulation behaviour.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json\n"
            "  python scripts/cds.py detect --signals packet.json --state state.json\n"
            "  python scripts/cds.py config --json\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("detect", parents=[common], help="rate the signals and compute the tension index")
    p.add_argument("--signals", required=True, help="signal packet JSON")
    p.add_argument("--out", help="write the detection record here")
    p.add_argument("--no-turn-advance", action="store_true", help="do not advance the turn counter")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("evaluate", parents=[common], help="score the evidence and route to a strategy")
    p.add_argument("--detection", required=True, help="detection record written by `detect`")
    p.add_argument("--signals", required=True, help="the same signal packet given to `detect`")
    p.add_argument("--out", help="write the evaluation record here")
    p.add_argument("--force", action="store_true", help="skip the state-machine precondition check")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("respond", parents=[common], help="close the loop and record the outcome")
    p.add_argument("--evaluation", required=True, help="evaluation record written by `evaluate`")
    p.add_argument("--out", help="write the response record here")
    p.set_defaults(func=cmd_respond)

    p = sub.add_parser("command", parents=[common], help="apply a user decision or control word")
    p.add_argument("word", help="处理 / 忽略 / 稍后 / 详情 / 恢复 / 关闭 CDS / 状态")
    p.set_defaults(func=cmd_command)

    p = sub.add_parser("status", parents=[common], help="print the current machine state")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", parents=[common], help="ambient one-shot loop: detect, evaluate and respond in one call")
    p.add_argument("--signals", required=True, help="signal packet JSON")
    p.add_argument("--out", help="write the full result here")
    p.add_argument("--no-turn-advance", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("validate", parents=[common], help="check a signal packet against its schema")
    p.add_argument("--signals", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("config", parents=[common], help="print the effective configuration and its hash")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("selftest", parents=[common], help="check config invariants and schema availability")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        config = _apply_overrides(config, getattr(args, "overrides", None))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (ConfigError, ValidationError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        return args.func(args, config)
    except (CliError, StageError, StateError, ValidationError) as exc:
        code = getattr(exc, "code", EXIT_STATE)
        print(f"error: {exc}", file=sys.stderr)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
