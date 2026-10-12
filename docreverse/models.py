"""Plain data classes shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------- document structure
@dataclass
class Block:
    """Smallest unit of document content.

    kind: heading | paragraph | list_item | table_row | field | code | comment | formula
    """
    kind: str
    text: str
    level: int = 0           # heading level, or list nesting depth
    ordered: bool = False    # list items: numbered (True) or bulleted (False)


@dataclass
class Section:
    index: int
    heading: str
    level: int
    blocks: List[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class Document:
    path: str
    title: str
    doc_type: str
    doc_code: Optional[str]
    sha: str
    mtime: float
    blocks: List[Block]
    sections: List[Section] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


# ---------------------------------------------------------------- extracted knowledge
@dataclass
class Mention:
    name: str
    kind: str       # role | team | system | artifact
    section: str
    sentence: str


@dataclass
class Relation:
    subject: str
    subject_kind: str
    predicate: str
    object: str
    object_kind: str
    section: str
    evidence: str
    source: str = "rules"   # rules | llm


@dataclass
class Step:
    n: int
    text: str
    actor: Optional[str] = None
    systems: List[str] = field(default_factory=list)
    is_decision: bool = False
    verb: str = ""


@dataclass
class Process:
    name: str
    section: str
    steps: List[Step]
    owner: Optional[str] = None
    owner_source: str = ""        # stated | inferred | ""
    trigger: Optional[str] = None
    systems: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    source: str = "rules"


@dataclass
class Rule:
    modality: str    # obligation | prohibition | recommendation | permission
    text: str
    section: str
    source: str = "rules"


@dataclass
class Fact:
    """A number with a unit found in text (a threshold, deadline, limit, price...)."""
    value: float
    unit: str
    raw: str
    sentence: str
    section: str


@dataclass
class Reference:
    target: str
    kind: str        # code | named
    evidence: str


@dataclass
class Term:
    term: str
    definition: str


@dataclass
class Extraction:
    mentions: List[Mention] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    processes: List[Process] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    facts: List[Fact] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)
    terms: List[Term] = field(default_factory=list)
