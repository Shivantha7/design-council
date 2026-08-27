"""Deterministic conformance gate. No LLM calls belong in this package."""

from design_council.gate.gate import RULES, GateConfigError, evaluate

__all__ = ["RULES", "GateConfigError", "evaluate"]
