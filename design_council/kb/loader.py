"""Loader for the IFRS/SLFRS knowledge base.

The knowledge base is a curated set of accounting-standard principles, each
recorded against the workflow steps it bears on. It is authored by hand in
ifrs_slfrs_kb.yaml and read here; nothing in this module writes to it.

render_for_prompt() produces the exact text the Accounting Standards agent
receives. That rendering is deterministic — stable ordering, no timestamps, no
dependence on dict iteration order — because the prompt an agent saw is part of
what makes a run reproducible. Two calls on the same file give byte-identical
output.

The `ref` field carries the paragraph citation and is "TBC" until verified by
hand against the standards texts. It is never filled in from memory.
"""

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from design_council.schemas.workflow_encoding import Domain

KB_PATH = Path(__file__).resolve().parent / "ifrs_slfrs_kb.yaml"

UNVERIFIED_REF = "TBC"


class Relevance(str, Enum):
    """How directly the principle bears on the workflows in the corpus."""

    CORE = "core"
    MARGINAL = "marginal"


class KBEntry(BaseModel):
    """One accounting-standard principle, tied to the steps it bears on."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    standard: str = Field(min_length=1)
    slfrs_equivalent: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    principle: str = Field(min_length=1)
    bears_on: list[str] = Field(min_length=1)
    domains: list[Domain] = Field(min_length=1)
    relevance: Relevance

    @model_validator(mode="after")
    def check_lists_have_no_duplicates(self) -> "KBEntry":
        for field_name in ("bears_on", "domains"):
            values = [
                v.value if isinstance(v, Enum) else v
                for v in getattr(self, field_name)
            ]
            duplicates = sorted({v for v in values if values.count(v) > 1})
            if duplicates:
                raise ValueError(
                    f"{self.id}: {field_name} lists {duplicates} more than once"
                )

        return self

    def is_ref_verified(self) -> bool:
        """False while the paragraph citation is still to be confirmed."""
        return self.ref != UNVERIFIED_REF


class KnowledgeBase(BaseModel):
    """The curated knowledge base as a whole."""

    model_config = ConfigDict(extra="forbid")

    entries: list[KBEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def check_ids_are_unique(self) -> "KnowledgeBase":
        ids = [entry.id for entry in self.entries]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate KB entry id(s): {duplicates}")

        return self

    def entry(self, entry_id: str) -> KBEntry:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry

        raise KeyError(f"no KB entry with id {entry_id!r}")

    def unverified_refs(self) -> list[str]:
        """Ids whose paragraph citation is still TBC, in id order."""
        return [e.id for e in self.sorted_entries() if not e.is_ref_verified()]

    def bears_on_step_ids(self) -> list[str]:
        """Every workflow step id referenced anywhere in the KB, deduplicated."""
        seen = []
        for entry in self.sorted_entries():
            for step_id in entry.bears_on:
                if step_id not in seen:
                    seen.append(step_id)

        return seen

    def sorted_entries(self) -> list[KBEntry]:
        """Entries in id order — the one ordering used for rendering."""
        return sorted(self.entries, key=lambda e: e.id)

    def render_for_prompt(self) -> str:
        """The exact text handed to the Accounting Standards agent.

        Deterministic by construction: entries in id order, fields in a fixed
        order, list values in the order they were authored, and nothing derived
        from the clock, the filesystem or dict iteration order.
        """
        lines = [
            "IFRS/SLFRS KNOWLEDGE BASE",
            f"{len(self.entries)} entries.",
            "",
            "Each entry records a principle from a reporting standard and the "
            "workflow steps it bears on.",
            "A ref of 'TBC' means the paragraph citation has not yet been "
            "verified against the standard text;",
            "treat the principle as stated here and do not cite a paragraph "
            "number for it.",
            "",
        ]

        for entry in self.sorted_entries():
            lines.append(f"[{entry.id}] {entry.topic}")
            lines.append(f"  standard:  {entry.standard} (SLFRS/LKAS: {entry.slfrs_equivalent})")
            lines.append(f"  ref:       {entry.ref}")
            lines.append(f"  relevance: {entry.relevance.value}")
            lines.append(f"  domains:   {', '.join(d.value for d in entry.domains)}")
            lines.append(f"  bears on:  {', '.join(entry.bears_on)}")
            lines.append(f"  principle: {entry.principle}")
            lines.append("")

        return "\n".join(lines)


def load_kb(path: Path | None = None) -> KnowledgeBase:
    """Read and validate the knowledge base.

    Raises FileNotFoundError if the file is absent, and ValidationError if any
    entry is malformed. There is no partial load: an invalid KB is not a KB.
    """
    source = KB_PATH if path is None else path

    with source.open() as handle:
        data = yaml.safe_load(handle)

    if isinstance(data, list):
        data = {"entries": data}

    return KnowledgeBase.model_validate(data)
