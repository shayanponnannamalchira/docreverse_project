"""Small text helpers used across the project."""
from __future__ import annotations

import re
from typing import List, Set

_ABBREVIATIONS = ["e.g.", "i.e.", "etc.", "vs.", "No.", "Dr.", "Mr.", "Ms.", "Mrs.", "Inc.", "Ltd.", "approx.", "St."]
_PLACEHOLDER = "\x00"


def split_sentences(text: str) -> List[str]:
    """Split text into sentences without breaking on abbreviations or decimals like 3.5."""
    t = " ".join(text.split())
    for abbr in _ABBREVIATIONS:
        t = t.replace(abbr, abbr.replace(".", _PLACEHOLDER))
    t = re.sub(r"(?<=\d)\.(?=\d)", _PLACEHOLDER, t)
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(\[])', t)
    return [p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip()]


# Words that often precede an entity name but are not part of it ("The Finance Manager", "Notify Line Manager").
STRIP_WORDS: Set[str] = set(
    """the a an our each any all your their this that these those if when after before once then also and or but
    please first next finally only both every which whenever until while notify send submit email contact inform
    escalate assign forward ask call page alert update create open review approve check confirm ensure obtain
    request route share report log record file enter use access""".split()
)

STOPWORDS: Set[str] = set(
    """a an the and or of to in on for with by at from as is are be been was were it this that these those within
    must shall should may can will not no if then than also any all each per into over under via their there
    which who whom whose when where while have has had having do does did done their its our your""".split()
)


def strip_leading(name: str) -> str:
    words = name.split()
    while words and words[0].lower() in STRIP_WORDS:
        words.pop(0)
    return " ".join(words)


def _stem(w: str) -> str:
    """Very light stemmer so 'approves'/'approve' and 'managers'/'manager' compare equal."""
    for suffix in ("es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4 and not w.endswith("ss"):
            return w[: -len(suffix)] if suffix == "s" or w.endswith(("ches", "shes", "xes")) else w[:-1]
    return w


def content_words(text: str) -> Set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z\-]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def norm_key(name: str) -> str:
    return " ".join(name.lower().split())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def shorten(text: str, n: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
