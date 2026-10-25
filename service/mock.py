"""A no-network model client for the service (LIVE_MOCK=1 and the tests).

Built on design_council.run_logging.MockClient. It answers each prompt kind the engine
sends: the resolution probe, round-1 and round-2 positions (recognised by the
"=== YOUR ROLE ===" section), and a TSS for the council synthesis ("=== COUNCIL
TRANSCRIPT ===") or for the budget-matched single agent (any other prompt). The TSS is
the identity redesign of the encoding, so a mock run is gate-clean with depth 0.
"""

import json

from design_council.run_logging import PROBE_PROMPT, MockClient
from design_council.schemas import WorkflowEncoding

from service.validation import identity_tss


class ServiceMockClient(MockClient):
    def __init__(self, encoding: WorkflowEncoding, resolved_model: str = "mock-model-1") -> None:
        super().__init__(resolved_model=resolved_model)
        self.tss_json = json.dumps(identity_tss(encoding).model_dump(mode="json"))

    def complete(self, prompt, **params):
        self.calls.append((prompt, dict(params)))
        if prompt == PROBE_PROMPT:
            return "ok", 5, 1, self.resolved_model
        if "=== YOUR ROLE ===" in prompt and "=== COUNCIL TRANSCRIPT ===" not in prompt:
            phase = "round 2" if "This is round 2." in prompt else "round 1"
            return f"Mock deliberation ({phase}).", 100, 80, self.resolved_model
        return self.tss_json, 500, 400, self.resolved_model
