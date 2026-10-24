"""Learning memory: remembers what worked (recipes), what the user said was wrong (corrections)
and how the user's voice gets misheard (vocab). No model training — hints are injected into prompts."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "learned.json"
_lock = threading.RLock()

_SEED_VOCAB = {
    "piecham": "PyCharm",
    "pi charm": "PyCharm",
    "pie charm": "PyCharm",
    "up work": "Upwork",
    "you tube": "YouTube",
}
_SKIP_AGENTS = {"voice_qa", "discussion"}
_STOPWORDS = {
    "the", "a", "an", "to", "me", "my", "please", "and", "in", "on", "of", "for", "is", "it",
    "can", "you", "i", "that", "this", "now",
}
_MAX_RECIPES = 200
_MAX_CORRECTIONS = 100
_MAX_RECIPE_STEPS = 12


def _empty() -> dict:
    return {"recipes": [], "corrections": [], "vocab": dict(_SEED_VOCAB)}


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        for k, v in _empty().items():
            data.setdefault(k, v)
        return data
    except FileNotFoundError:
        return _empty()
    except Exception as exc:
        log.warning("learned.json unreadable (%s) — starting fresh", exc)
        return _empty()


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _norm(text: str) -> str:
    return " ".join(sorted(_tokens(text)))


# ── Vocabulary (voice mishearings) ────────────────────────────────────────────

def apply_vocab(text: str) -> str:
    with _lock:
        vocab = _load()["vocab"]
    for wrong, right in sorted(vocab.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    return text


def teach_vocab(wrong: str, right: str) -> None:
    wrong, right = wrong.strip().lower(), right.strip()
    if not wrong or not right or wrong == right.lower():
        return
    with _lock:
        data = _load()
        data["vocab"][wrong] = right
        _save(data)
    log.info("Learned vocab: %r -> %r", wrong, right)


# ── Recipes (successful approaches) ───────────────────────────────────────────

def record_success(instruction: str, agent: str, steps: list[dict]) -> bool:
    """Store the tool sequence of a completed task. Steps: dicts with tool/description/parameters."""
    if agent in _SKIP_AGENTS or not steps or len(steps) > _MAX_RECIPE_STEPS:
        return False
    slim = [
        {"tool": s["tool"], "description": s.get("description", "")[:100], "parameters": s.get("parameters", {})}
        for s in steps if s.get("tool") not in ("no_op", "ask_user")
    ]
    if not slim:
        return False
    key = _norm(instruction)
    with _lock:
        data = _load()
        for r in data["recipes"]:
            if r["agent"] == agent and _norm(r["instruction"]) == key:
                r.update(steps=slim, instruction=instruction, ts=time.time(), count=r.get("count", 1) + 1)
                break
        else:
            data["recipes"].append({
                "instruction": instruction, "agent": agent, "steps": slim,
                "count": 1, "verified": False, "ts": time.time(),
            })
            data["recipes"] = data["recipes"][-_MAX_RECIPES:]
        _save(data)
    return True


def mark_verified(instruction: str, agent: str) -> bool:
    """User said the result was right: pin the recipe so it is preferred."""
    key = _norm(instruction)
    with _lock:
        data = _load()
        for r in data["recipes"]:
            if r["agent"] == agent and _norm(r["instruction"]) == key:
                r["verified"] = True
                _save(data)
                return True
    return False


def record_failure(instruction: str, agent: str, note: str) -> None:
    """User said the result was wrong: drop the recipe and remember the complaint."""
    key = _norm(instruction)
    with _lock:
        data = _load()
        data["recipes"] = [
            r for r in data["recipes"] if not (r["agent"] == agent and _norm(r["instruction"]) == key)
        ]
        data["corrections"].append({"instruction": instruction, "agent": agent, "note": note[:300], "ts": time.time()})
        data["corrections"] = data["corrections"][-_MAX_CORRECTIONS:]
        _save(data)


def hints_for(instruction: str, agent: str) -> str:
    """Prompt block with similar past successes and user corrections; empty string if none."""
    with _lock:
        data = _load()

    scored = []
    for r in data["recipes"]:
        if r["agent"] != agent:
            continue
        sim = _similarity(instruction, r["instruction"])
        if sim >= 0.5:
            scored.append((sim + (0.3 if r.get("verified") else 0) + min(r.get("count", 1), 5) * 0.02, r))
    scored.sort(key=lambda x: -x[0])

    parts: list[str] = []
    for _, r in scored[:2]:
        steps = "\n".join(
            f'    {i + 1}. {s["tool"]} {json.dumps(s["parameters"], ensure_ascii=False)}'
            for i, s in enumerate(r["steps"])
        )
        tag = "confirmed by the user" if r.get("verified") else "completed earlier"
        parts.append(f'  Task "{r["instruction"]}" ({tag}) used:\n{steps}')

    notes = [
        c for c in data["corrections"]
        if c.get("agent") == agent and _similarity(instruction, c["instruction"]) >= 0.3
    ]
    notes.sort(key=lambda c: -c["ts"])

    out = ""
    if parts:
        out += (
            "LEARNED FROM PAST SUCCESSES — a similar task worked this way. Reuse the same approach, "
            "adapting parameters (URLs, search text) to the new instruction:\n" + "\n".join(parts) + "\n"
        )
    if notes:
        out += "USER CORRECTIONS — avoid repeating these mistakes:\n" + "\n".join(
            f'  - For "{c["instruction"]}" the user said: {c["note"]}' for c in notes[:3]
        ) + "\n"
    return out
