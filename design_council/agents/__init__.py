"""Baseline and council agents.

Only anthropic_client imports a provider SDK; everything else works against the
ModelClient protocol so the whole pipeline is testable offline.
"""

from design_council.agents.baseline import BaselineError, build_prompt, run_baseline

__all__ = ["BaselineError", "build_prompt", "run_baseline"]
