"""Deterministic text checks. No AI here - this is the 'code decides' half.

- Quote verification: every quote the AI cites must literally exist in the
  source text. This is the hallucination guard behind 'no score above 1
  without a verbatim quote'.
- Banned-word filter: enforces process-not-person language in feedback.
- Grounding check: a generated task must reference the candidate's own project.
"""
from __future__ import annotations

import re
from typing import Iterable

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
})
_WS = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")
MIN_QUOTE_CHARS = 6
MIN_FRAGMENT_CHARS = 8


def normalize(text: str) -> str:
    t = (text or "").translate(_QUOTE_MAP).lower()
    return _WS.sub(" ", t).strip()


def _strip_edges(t: str) -> str:
    return t.strip(" \"'`.,;:!?()[]{}")


def quote_in_source(quote: str, source: str) -> bool:
    """True if `quote` appears verbatim in `source`, ignoring case, whitespace,
    curly-vs-straight quotes and dashes. An ellipsis inside the quote is
    allowed: each fragment must appear, in order."""
    q = _strip_edges(normalize(quote))
    if len(q) < MIN_QUOTE_CHARS:
        return False
    src = normalize(source)
    fragments = [_strip_edges(f) for f in _ELLIPSIS.split(q)]
    fragments = [f for f in fragments if f]
    if not fragments:
        return False
    if len(fragments) == 1:
        return fragments[0] in src
    pos = 0
    for frag in fragments:
        if len(frag) < MIN_FRAGMENT_CHARS:
            return False
        idx = src.find(frag, pos)
        if idx == -1:
            return False
        pos = idx + len(frag)
    return True


# --------------------------------------------------------------------------
# Banned vocabulary (growth-mindset enforcement)
# --------------------------------------------------------------------------
BANNED_REPLACEMENTS = {
    "failed": "didn't yet",
    "inadequate": "not yet sufficient",
    "poor": "limited",
    "weak": "thin",
    "unqualified": "not yet evidenced",
    "lacks": "doesn't yet show",
    "deficient": "incomplete",
    "incompetent": "not yet shown",
    "disappointing": "not yet there",
}
BANNED_PHRASES = {
    "you should have": "a next step is to",
    "you clearly": "you",
    "you're naturally": "you're",
    "you are naturally": "you are",
}
_BANNED_RE = re.compile(r"\b(" + "|".join(map(re.escape, BANNED_REPLACEMENTS)) + r")\b", re.IGNORECASE)
_PHRASE_RE = re.compile(r"\b(" + "|".join(map(re.escape, BANNED_PHRASES)) + r")\b", re.IGNORECASE)


def find_banned(text: str) -> list[str]:
    found = {m.group(1).lower() for m in _BANNED_RE.finditer(text or "")}
    found |= {m.group(1).lower() for m in _PHRASE_RE.finditer(text or "")}
    return sorted(found)


def _match_case(original: str, replacement: str) -> str:
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def sanitize(text: str) -> str:
    if not text:
        return text
    text = _PHRASE_RE.sub(lambda m: _match_case(m.group(1), BANNED_PHRASES[m.group(1).lower()]), text)
    return _BANNED_RE.sub(lambda m: _match_case(m.group(1), BANNED_REPLACEMENTS[m.group(1).lower()]), text)


# --------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------
_STOP = {
    "about", "after", "again", "their", "there", "these", "those", "which", "while",
    "would", "could", "should", "using", "based", "built", "model", "models", "project",
    "projects", "made", "where", "because", "other", "first", "second", "third", "being",
    "every", "under", "until", "within", "without", "student", "students", "learned",
    "developed", "worked", "create", "created", "small", "large", "simple", "system",
    "data", "dataset", "train", "trained", "training", "test", "tested", "results",
}
_WORD = re.compile(r"[a-z][a-z0-9+#.\-]{4,}")


def distinctive_tokens(texts: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for t in texts:
        for w in _WORD.findall(normalize(t)):
            w = w.strip(".-")
            if len(w) >= 5 and w not in _STOP:
                tokens.add(w)
    return tokens


def is_grounded(task_text: str, tools: list[str], project_texts: list[str]) -> bool:
    """A task is grounded if it names one of the candidate's own tools, or
    shares at least two distinctive words with their project description."""
    t = normalize(task_text)
    for tool in tools or []:
        tool_n = normalize(tool)
        if len(tool_n) >= 2 and re.search(r"(?<![a-z0-9])" + re.escape(tool_n) + r"(?![a-z0-9])", t):
            return True
    task_tokens = distinctive_tokens([task_text])
    return len(task_tokens & distinctive_tokens(project_texts)) >= 2


def word_count(text: str) -> int:
    return len((text or "").split())
