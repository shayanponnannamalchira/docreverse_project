"""Business rules: sentences that oblige, prohibit, recommend or permit something."""
from __future__ import annotations

import re
from typing import Optional

from ..models import Rule
from ..textutil import shorten

PROHIBIT = re.compile(r"\b(must not|shall not|may not|cannot|can not|is prohibited|are prohibited|not permitted|not allowed|never|forbidden|must never)\b", re.I)
OBLIGE = re.compile(r"\b(must|shall|is required to|are required to|required to|is mandatory|are mandatory|mandatory|needs to|need to|has to|have to)\b", re.I)
RECOMMEND = re.compile(r"\b(should|recommended|ought to|is encouraged|are encouraged|best practice)\b", re.I)
PERMIT = re.compile(r"\b(may|is permitted|are permitted|is allowed|are allowed)\b", re.I)


def extract_rule(sentence: str, section: str) -> Optional[Rule]:
    if len(sentence.split()) < 5 or sentence.rstrip().endswith("?"):
        return None
    for name, rx in (("prohibition", PROHIBIT), ("obligation", OBLIGE), ("recommendation", RECOMMEND), ("permission", PERMIT)):
        if rx.search(sentence):
            return Rule(name, shorten(sentence, 300), section)
    return None
