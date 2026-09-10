"""Shared test bootstrap: put ``scripts/`` on the path and expose helpers."""

from __future__ import annotations

import copy
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cds_config import load_config  # noqa: E402

BASE_CONFIG = load_config()

SCRATCH_ROOT = REPO_ROOT / "tests" / ".scratch"


@contextmanager
def scratch_dir() -> Iterator[Path]:
    """A disposable directory *inside the repository*.

    ``tempfile.TemporaryDirectory`` is deliberately avoided: a sandboxed or
    locked-down test runner may deny writes outside the working tree, and a test
    suite that fails for lack of a writable ``%TEMP%`` is a portability defect
    rather than a finding.
    """
    path = SCRATCH_ROOT / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def base_packet(**overrides):
    """A minimal valid packet that reaches `alert` on the dissonance channel.

    Baseline arithmetic (asserted in test_index.py so the fixture cannot drift):
      volition_self = 0.80 * 0.90 = 0.72
      T = 0.35*0.80 + 0.25*0.60 + 0.20*0.72 + 0.12*0.60 + 0.08*0.50 = 0.686
    """
    packet = {
        "run_id": "test_run",
        "turn_id": 1,
        "annotator": "test",
        "relation": {
            "type": "evidence_vs_stance",
            "opposition": 0.80,
            "specificity": 0.60,
            "rationale": "stance vs evidence",
        },
        "stance": {
            "id": "stance_001",
            "claim": "X is reliable here",
            "source": "prior_conversation",
            "confidence": 0.70,
            "commitment": 0.60,
            "public_commitment": 0.55,
            "volition": 0.80,
            "self_relevance": 0.90,
        },
        "evidence": [
            {
                "id": "ev_001",
                "claim": "X fails in most deployments",
                "source": "paper",
                "carries_conflict": True,
                "novelty": 0.50,
                "relevance": 0.80,
                "credibility": 0.55,
                "recency": 0.70,
                "independence": 0.40,
                "consistency": 0.50,
                "quote": "X fails in 62% of deployments.",
            }
        ],
        "user_pressure": 0.30,
        "evidence_conflict_unresolved": 0.10,
        "consistency_gate": {"internal_contradiction": 0.0},
        "perception": {"confidence": 0.80, "ambiguities": []},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(packet.get(key), dict):
            packet[key] = {**packet[key], **value}
        else:
            packet[key] = copy.deepcopy(value)
    return packet


def config_with(**overrides):
    """Deep-merged copy of the shipped config."""
    config = copy.deepcopy(BASE_CONFIG)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            for inner_key, inner_value in value.items():
                if isinstance(inner_value, dict) and isinstance(config[key].get(inner_key), dict):
                    config[key][inner_key] = {**config[key][inner_key], **inner_value}
                else:
                    config[key][inner_key] = copy.deepcopy(inner_value)
        else:
            config[key] = copy.deepcopy(value)
    return config
