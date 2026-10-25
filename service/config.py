"""Service settings, read from the environment (.env via design_council.run_logging.load_env)."""

import os
from pathlib import Path

from pydantic import BaseModel

from design_council.run_logging import DEFAULT_REQUESTED_MODEL, load_env

REPO_ROOT = Path(__file__).resolve().parent.parent

# Expected cost per run in USD, from the held-out set (docs/RESULTS_HELDOUT_efficiency.md):
# council mean $1.42, budget-matched single agent mean $0.07, at $2/M input and $10/M output.
ESTIMATE_USD = {"council": 1.42, "baseline": 0.07}
PRICE_INPUT_PER_M = 2.0
PRICE_OUTPUT_PER_M = 10.0


class Settings(BaseModel):
    runs_live_root: Path = REPO_ROOT / "runs_live"
    daily_cap_usd: float = 20.0
    password: str | None = None
    max_workers: int = 2
    mock: bool = False
    requested_model: str = DEFAULT_REQUESTED_MODEL

    @property
    def db_path(self) -> Path:
        return self.runs_live_root / "jobs.sqlite"

    @property
    def jobs_root(self) -> Path:
        return self.runs_live_root / "_jobs"


def settings_from_env() -> Settings:
    load_env()
    return Settings(
        runs_live_root=Path(os.environ.get("LIVE_RUNS_ROOT", REPO_ROOT / "runs_live")),
        daily_cap_usd=float(os.environ.get("LIVE_DAILY_CAP_USD", "20")),
        password=os.environ.get("LIVE_PASSWORD") or None,
        max_workers=int(os.environ.get("LIVE_MAX_WORKERS", "2")),
        mock=os.environ.get("LIVE_MOCK", "") == "1",
        requested_model=os.environ.get("LIVE_MODEL", DEFAULT_REQUESTED_MODEL),
    )
