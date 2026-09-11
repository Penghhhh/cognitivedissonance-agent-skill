"""Which language the component speaks on this turn.

The component has always shipped every runtime string in both Chinese and English,
but which one it used was a **config constant**: ``skill.language`` was pinned at
load time, so a user who switched languages mid-session kept getting cards in the
language the config named. That is wrong for the thing this is meant to be. A
transparency card is addressed to the person reading it, and the language of the
conversation is part of what the card is transparent about.

v0.5.1 makes the language a per-turn resolution with three inputs, in order:

1. **An explicit override** — ``--lang zh|en`` on any command. The host model knows
   what language the user is writing in, and this repository's architecture says
   perception is the model's job. This is the input to prefer.
2. **The packet itself** — read off the text the perceiver wrote. See
   ``detect_language`` for which fields are read and why.
3. **The session** — what the previous turn of this run resolved to, read from the
   state file, so a command like ``cds.py command 处理`` answers in the language the
   conversation is already in rather than in a config default.
4. **``skill.language_fallback``** — the last resort, default ``en``.

``skill.language: "auto"`` is the shipped default and turns 2-4 on. Pinning it to
``"zh"`` or ``"en"`` disables the whole mechanism and restores the pre-v0.5.1
behaviour, which is what an ablation condition needs: for a study the language is a
controlled factor, not a convenience, so the pin has to remain available and has to
win over everything except ``--lang``.

The resolved value is written back into the config for the run, so every renderer,
the log envelope and the recorded ``config_hash`` all describe the language that was
actually used. Two runs whose only difference is the language they rendered in are
different observations and should not share a hash.
"""

from __future__ import annotations

from typing import Any

AUTO = "auto"
SUPPORTED = ("zh", "en")

#: Unicode blocks counted as Chinese. Deliberately excludes Hiragana, Katakana and
#: Hangul: a Japanese or Korean packet is not a Chinese packet, and counting kana as
#: CJK would label it as one. Such a packet falls through to the session hint and
#: then the fallback, which is the honest answer while the component has no ja/ko
#: strings.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x20000, 0x2FA1F),  # Extension B and beyond
)


def _counts(text: str) -> tuple[int, int]:
    """Return ``(chinese_characters, latin_letters)`` for one string."""
    cjk = 0
    latin = 0
    for char in text:
        code = ord(char)
        if any(low <= code <= high for low, high in _CJK_RANGES):
            cjk += 1
        elif char.isascii() and char.isalpha():
            latin += 1
    return cjk, latin


def _classify(text: Any) -> str | None:
    """One string's verdict, or ``None`` when it carries no letters at all."""
    if not isinstance(text, str) or not text.strip():
        return None
    cjk, latin = _counts(text)
    if cjk == 0 and latin == 0:
        return None
    if cjk == 0:
        return "en"
    if latin == 0:
        return "zh"
    # A Chinese sentence carrying English technical terms still has far fewer CJK
    # characters than the Latin word count suggests, because a Chinese character
    # carries more meaning per glyph. The 2:1 allowance is what keeps "该方案在当前
    # 规模下是可靠的" labelled Chinese when the claim also names an English product.
    return "zh" if cjk * 2 >= latin else "en"


def sniff_texts(signals: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The packet fields the language is read off, as ``(field, text)`` pairs.

    Only the text the **perceiver wrote in the conversation's own language** is
    eligible:

    * ``stance.claim`` first, because for ``prior_conversation`` and
      ``user_message`` sources it is the agent's or the user's own words — the
      conversation's language by definition;
    * then ``relation.rationale``, which the perceiver writes about the conflict;
    * then each ``evidence[].claim``.

    ``evidence[].quote`` is deliberately **excluded**. It is a verbatim span, and a
    Chinese conversation about an English paper has English quotes in it; letting a
    long quotation vote would flip the card to English on exactly the turn where the
    user most needs to read it. ``id`` and ``source`` fields are excluded for the
    same reason in the other direction: they are structural identifiers, always
    Latin, and they must never be evidence of anything.
    """
    if not isinstance(signals, dict):
        return []
    fields: list[tuple[str, str]] = []
    relation = signals.get("relation") or {}
    stance = signals.get("stance") or {}
    if isinstance(stance.get("claim"), str):
        fields.append(("stance.claim", stance["claim"]))
    if isinstance(relation.get("rationale"), str):
        fields.append(("relation.rationale", relation["rationale"]))
    for index, item in enumerate(signals.get("evidence") or []):
        if isinstance(item, dict) and isinstance(item.get("claim"), str):
            fields.append((f"evidence[{index}].claim", item["claim"]))
    return fields


def detect_language(signals: dict[str, Any] | None) -> str | None:
    """Read the conversation language off the packet, or ``None`` if it cannot.

    Per field and then voted, rather than summed across fields. Summing lets one
    long foreign-language evidence claim outvote a short Chinese stance, which is
    the common shape of the case this is for: a Chinese conversation with an English
    source quoted into it. The stance claim is the strongest single signal because
    it is the speaker's own words, so it decides on its own when it is conclusive.
    """
    fields = sniff_texts(signals)
    if not fields:
        return None

    by_name = dict(fields)
    for decisive in ("stance.claim", "relation.rationale"):
        verdict = _classify(by_name.get(decisive))
        if verdict is not None:
            return verdict

    votes: list[str] = []
    for _, text in fields:
        verdict = _classify(text)
        if verdict is not None:
            votes.append(verdict)
    if not votes:
        return None
    return "zh" if votes.count("zh") > votes.count("en") else "en"


def explain_language(
    config: dict[str, Any],
    signals: dict[str, Any] | None = None,
    *,
    override: str | None = None,
    session: str | None = None,
) -> tuple[str, str]:
    """Resolve the language **and say which input decided it**.

    The second element is one of ``override``, ``pinned``, ``packet``, ``session``
    or ``fallback``, and it is recorded in the turn's log record. A study needs it:
    "the participant's cards were in Chinese" means something different depending on
    whether the language was pinned by the condition, inferred from what they wrote,
    or silently defaulted because there was nothing to read.
    """
    if override:
        value = str(override).strip().lower()
        if value in SUPPORTED:
            return value, "override"

    skill = config.get("skill") or {}
    pinned = str(skill.get("language", AUTO)).strip().lower()
    if pinned in SUPPORTED:
        return pinned, "pinned"

    sniffed = detect_language(signals)
    if sniffed:
        return sniffed, "packet"

    if session in SUPPORTED:
        return str(session), "session"

    fallback = str(skill.get("language_fallback", "en")).strip().lower()
    return (fallback if fallback in SUPPORTED else "en"), "fallback"


def resolve_language(
    config: dict[str, Any],
    signals: dict[str, Any] | None = None,
    *,
    override: str | None = None,
    session: str | None = None,
) -> str:
    """Resolve the language for one turn. See the module docstring for the order."""
    return explain_language(config, signals, override=override, session=session)[0]


def apply_language(
    config: dict[str, Any],
    signals: dict[str, Any] | None = None,
    *,
    override: str | None = None,
    session: str | None = None,
) -> tuple[str, str]:
    """Resolve the language and write it back into ``config`` for the rest of the run.

    Every renderer, the log envelope and the recorded ``config_hash`` read
    ``config["skill"]["language"]``, so writing the resolved value here is what makes
    the whole program agree about the language without threading a new argument
    through thirty functions. It is also why the resolved language is visible in the
    hash: two runs that differ only in rendering language are different observations.

    Returns ``(language, source)`` so the caller can put both in the turn's record.
    """
    resolved, source = explain_language(config, signals, override=override, session=session)
    config.setdefault("skill", {})["language"] = resolved
    return resolved, source


def language_of(config: dict[str, Any]) -> str:
    """The language in force. For modules that only need to read it."""
    value = str((config.get("skill") or {}).get("language", "en")).strip().lower()
    return value if value in SUPPORTED else "en"
