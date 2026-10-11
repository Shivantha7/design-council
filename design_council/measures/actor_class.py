"""Step actor classification for the productivity analysis (docs/PRODUCTIVITY_METHOD.md section 2).

EXPLORATORY, not pre-registered. Every step of an original encoding or a council
TSS is classified HUMAN, HYBRID or AGENT by deterministic keyword rules over its
actor field, with the description consulted only to raise flags. The rules are
fixed in code here. Every step whose classification depends on an author
decision is flagged, and the decisions are applied through `overrides`, never by
editing the rules after seeing results.

    HUMAN   a person performs the step (with or without conventional tools such
            as an ERP)
    HYBRID  an AI agent performs the step and a person reviews, approves or
            confirms it
    AGENT   an AI agent performs the step; only exceptions go to a person

Rules, applied to the actor string in this order:

    R1  No automation term (AI_TERMS or AUTOMATION_TERMS) in the actor, once
        conventional-tool qualifiers such as "ERP" are set aside: HUMAN.
    R2  Automation term present and the named person handles only exceptions,
        fallbacks or flagged items (EXCEPTION_TERMS): AGENT.
    R3  Automation term present and the named person is assisted by it, or
        reviews, approves, confirms, oversees or signs off its work
        (ASSIST_TERMS or REVIEW_TERMS): HYBRID.
    R4  Automation term present and no person named in a role: AGENT.

Flags (the step goes to the author's review list):

    G1  automation is deterministic (engine, rules, pipeline, system-executed)
        with no AI term: whether that counts as an "AI agent" is a global
        author decision
    G2  the person is the primary performer and the automation only assists
        (R3 via ASSIST_TERMS): HYBRID by rule, but section 2 says the agent
        performs
    G3  the person only owns or governs the policy, not each item: AGENT or
        HYBRID is an author decision
    A1  exception cue and review/assist cue both present
    A2  alternatives or conditional lanes in the actor ("/", "or", "where
        feasible", separate lanes)
    A3  the actor names no automation but the description does (an agent may
        be performing)
    A4  an automation term may describe something other than the performer
        (segregation, escalation, logistics only, mechanical push)

Before matching, "distinct from ..." and "independent of ..." clauses are removed
from the actor: they name other parties for segregation, not the performer.
"""

import re
from typing import NamedTuple

HUMAN, HYBRID, AGENT = "HUMAN", "HYBRID", "AGENT"

AI_TERMS = re.compile(
    r"\b(agents?|AI|copilot|LLM|machine[- ]learning|bot)\b|AI-|-agent\b", re.IGNORECASE)
AUTOMATION_TERMS = re.compile(
    r"\b(automat\w*|engines?|system-executed|system-enforced|system identity|pipeline|"
    r"tooling|tool)\b|^\s*system\b|\bsystem\s*\(|\brelease control system\b|"
    r"\bpublishing system\b|\bextraction system\b|\bload system\b",
    re.IGNORECASE)
# Conventional tools that do not make a step agentic on their own (section 2).
CONVENTIONAL = re.compile(r"\bERP\b( (matching engine|retrieval|automation))?", re.IGNORECASE)
EXCEPTION_TERMS = re.compile(
    r"exception|fallback|flagged|on stall|override|failed[- ]delivery|failed-payment|"
    r"anomaly reviewer|manual-completion|manual-capture", re.IGNORECASE)
ASSIST_TERMS = re.compile(
    r"supported by|assisted|assisting|\bwith (an? )?(AI|automated|agent|drafting|computation|"
    r"payment|posting|screening|reconciliation|matching|ingestion|load|extraction|"
    r"gated automated)|copilot|drafting tool|\bwith\b.*\b(agent|engine|system|tool|pipeline|job)\b",
    re.IGNORECASE)
REVIEW_TERMS = re.compile(
    r"overseen|oversight|review|approv|sign-?off|confirm|supervis|attestor|validator|"
    r"adjudicat|triggered by|human-triggered|monitors?\b|steward|accountable reviewer|"
    r"under accountant oversight|releases variances", re.IGNORECASE)
POLICY_OWNER_ONLY = re.compile(
    r"policy owner|policy content|owned and periodically re-approved|governed by|"
    r"accountable for the policy|accountable policy owner|control owner accountable",
    re.IGNORECASE)
ALTERNATIVES = re.compile(
    r"\s/\s|\bor\b|where feasible|lane\)|lane;|; [A-Z]", re.IGNORECASE)

SEGREGATION_CLAUSE = re.compile(r"\b(distinct from|independent of)\b[^;)]*", re.IGNORECASE)
NON_PERFORMER = re.compile(
    r"system-enforced (distinct role|delegation)|automatic next-level escalation|"
    r"logistics only|mechanical push|non-decisioning|no write/decision authority",
    re.IGNORECASE)

APPROVAL_STEP = re.compile(
    r"\b(approv\w*|authoris\w*|authoriz\w*|sign-?off|attest\w*|certif\w*)\b", re.IGNORECASE)


class Classification(NamedTuple):
    cls: str
    rule: str
    flags: tuple[str, ...]


def _automation_in(actor: str) -> tuple[bool, bool]:
    """(has AI term, has deterministic-automation term), with ERP-only qualifiers set aside."""
    stripped = CONVENTIONAL.sub("", actor)
    return bool(AI_TERMS.search(stripped)), bool(AUTOMATION_TERMS.search(stripped))


def classify(actor: str, description: str = "") -> Classification:
    actor = SEGREGATION_CLAUSE.sub("", actor)
    has_ai, has_auto = _automation_in(actor)
    flags = []
    if NON_PERFORMER.search(actor):
        flags.append("A4")
    if ALTERNATIVES.search(actor):
        flags.append("A2")

    if not (has_ai or has_auto):
        d_ai, d_auto = _automation_in(description)
        if d_ai:
            flags.append("A3")
        return Classification(HUMAN, "R1", tuple(flags))

    if has_auto and not has_ai:
        flags.append("G1")

    exception = bool(EXCEPTION_TERMS.search(actor))
    assist = bool(ASSIST_TERMS.search(actor))
    review = bool(REVIEW_TERMS.search(actor))
    policy_only = bool(POLICY_OWNER_ONLY.search(actor))

    if exception:
        if assist or review:
            flags.append("A1")
        return Classification(AGENT, "R2", tuple(flags))
    if policy_only and not assist:
        flags.append("G3")
        return Classification(AGENT, "R4", tuple(flags))
    if assist or review:
        if assist and not review:
            flags.append("G2")
        return Classification(HYBRID, "R3", tuple(flags))
    return Classification(AGENT, "R4", tuple(flags))


def is_approval_step(name: str) -> bool:
    """Explicit approval step for the section 5 counts: approval vocabulary in the step name."""
    return bool(APPROVAL_STEP.search(name))


# --- author decisions, 11 Oct 2026 (docs/PRODUCTIVITY_DECISIONS.md) ------------
#
# G1 yes (primary): deterministic automation counts as automated.
#    Declared variant "agentic-only": every G1 step is HUMAN.
# G2 HYBRID, G3 AGENT, G4 defaults (all as the rules above).
# A3 keep HUMAN; A1, A2 keep defaults.
# A4 HUMAN, unless the actor also names an automated lane that performs the
#    step (PERFORMING_LANE), in which case the default stands.

PRIMARY, AGENTIC_ONLY = "primary", "agentic-only"

PERFORMING_LANE = re.compile(
    r"\b(automat\w*|system-executed|engine|gate)\b[^;]*\b(for clean|lane)\b", re.IGNORECASE)


def decided_class(actor: str, description: str = "", variant: str = PRIMARY) -> str:
    """The class used in the productivity analysis, after the author's decisions."""
    if variant not in (PRIMARY, AGENTIC_ONLY):
        raise ValueError(f"unknown variant {variant!r}")
    c = classify(actor, description)
    cls = c.cls
    if "A4" in c.flags and not PERFORMING_LANE.search(actor):
        cls = HUMAN
    if variant == AGENTIC_ONLY and "G1" in c.flags:
        cls = HUMAN
    return cls
