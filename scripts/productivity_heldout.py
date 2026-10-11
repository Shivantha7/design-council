"""Structural Productivity Potential (SPP), held-out council redesigns. EXPLORATORY.

    python scripts/productivity_heldout.py --set-name heldout-v1 --out docs/RESULTS_PRODUCTIVITY.md

Implements docs/PRODUCTIVITY_METHOD.md sections 3 to 6 (committed a67c2af), with
the author's classification decisions (docs/PRODUCTIVITY_DECISIONS.md, 4ab2958),
for the PRIMARY classification and the declared AGENTIC-ONLY variant. Standard
library only: numpy is not in requirements.lock, so this needs no dependency
change. Read-only on runs. No model calls.

Section 3 model, per council run:
    H  = sum over original steps s of t_s x r(class of carrying step) x m(disposition of s)
    PI = 1 - H / H_original, with H_original = 1 (every original step is HUMAN,
         weights sum to 1)
    r(HUMAN) = 1, r(HYBRID) = r_h, r(AGENT) = e x k
    m = 1 for retained or restructured; the drawn m for merged or absorbed

Implementation choices where the method is silent, fixed here before the first
computation:
    C1  eliminated: the method gives no factor. The 33 council runs contain no
        eliminated disposition (Table X.4). The script raises if it meets one,
        rather than invent a value.
    C2  several carrying target steps: "most human-intensive class" is taken by
        class order HUMAN > HYBRID > AGENT, independent of the drawn values.
    C3  per draw: one r_h, one k, one m; one e for the transactional subgroup and
        one for the judgment-dense subgroup; one Dirichlet weight vector t per
        workflow, shared by that workflow's runs.
    C4  per workflow: PI over all (draw, run) pairs; median and 90% interval
        (5th and 95th percentiles).
    C5  pooled PI: the median across the 7 workflows of the per-workflow median PI.
        Workflow-level bootstrap: 10,000 resamples of the 7 workflows with
        replacement, the statistic recomputed each time; 90% percentile interval.
        Subgroups use the same statistic and bootstrap within the subgroup.
    C6  PRCC: per draw, outcome = pooled PI for that draw (the median across
        workflows of the per-workflow mean PI over runs). Predictors: the scalar
        parameters r_h, e_transactional, e_judgment, k, m. The Dirichlet weights
        are a vector and get no single coefficient. Spearman-type: rank both
        sides, regress out the other predictors, correlate the residuals.
    C7  one-at-a-time: each scalar parameter at its minimum and maximum, the
        others at central values (r_h 0.65, e at its midpoint, k 1.25, m 0.85,
        equal weights t_s = 1/n). Outcome: pooled PI as in C6.
    C8  worst case (section 4): r_h 0.85, e at its maximum, k 1.5, m 1.0, all
        weight on the original step with the largest r x m in that run, so
        PI = 1 - max_s r x m. Per workflow: the minimum over its runs (the worst run).
    C9  primary and variant use the same random draws (common random numbers).
    C10 section 5 counts use the step order in the encoding or TSS. Base role is
        the actor text before the first "(", "," or ";", case-folded.
"""

import argparse
import json
import platform
import random
import re
import sys
from pathlib import Path
from statistics import mean, median

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from design_council.measures.actor_class import (  # noqa: E402
    AGENT, AGENTIC_ONLY, HUMAN, HYBRID, PRIMARY, decided_class, is_approval_step,
)

RUNS_ROOT = REPO_ROOT / "runs"
SEED = 20261011
DRAWS = 10_000
BOOTSTRAP = 10_000
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
TRANSACTIONAL = {"P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01", "R2R-ACR-01"}
SUBGROUP = {wf: ("transactional" if wf in TRANSACTIONAL else "judgment-dense") for wf in TEMPLATE_WORKFLOWS}
E_RANGE = {"transactional": (0.10, 0.30), "judgment-dense": (0.20, 0.50)}
RH = (0.45, 0.65, 0.85)   # triangular low, mode, high
K = (1.0, 1.5)
M = (0.70, 1.00)
INTENSITY = {HUMAN: 2, HYBRID: 1, AGENT: 0}
VARIANTS = [PRIMARY, AGENTIC_ONLY]


# --- data ----------------------------------------------------------------------


def base_role(actor: str) -> str:
    return re.split(r"[(,;]", actor, maxsplit=1)[0].strip().casefold()


def load(set_name: str, runs_root: Path):
    events = [json.loads(l) for l in (runs_root / f"_set-{set_name}.ledger.jsonl").read_text().splitlines()]
    paths = next(e for e in events if e["event"] == "set_started")["workflows"]
    council = {wf: [] for wf in TEMPLATE_WORKFLOWS}
    for e in events:
        if e["event"] == "finished" and e["status"] == "ok" and e["condition"] == "council":
            council[e["workflow_id"]].append(e["run_id"])
    encodings = {wf: json.loads((REPO_ROOT / paths[wf]).read_text()) for wf in TEMPLATE_WORKFLOWS}
    tss = {r: json.loads((runs_root / r / "tss.json").read_text())
           for runs in council.values() for r in runs}
    return encodings, council, tss


def carried(encoding: dict, tss: dict, variant: str) -> list[tuple[str, str]]:
    """Per original step, in encoding order: (class of carrying step, disposition)."""
    steps = {s["step_id"]: s for s in tss["steps"]}
    by_baseline = {d["baseline_step_id"]: d for d in tss["disposition_mapping"]}
    out = []
    for s in encoding["steps"]:
        d = by_baseline[s["step_id"]]
        if d["disposition"] == "eliminated":
            raise ValueError(f"{tss['workflow_id']} {s['step_id']}: eliminated, undefined by "
                             "the method (choice C1)")
        classes = [decided_class(steps[t]["actor"], steps[t]["description"], variant)
                   for t in d["target_step_ids"]]
        out.append((max(classes, key=INTENSITY.get), d["disposition"]))
    return out


def structural(steps: list[dict], variant: str) -> dict:
    classes = [decided_class(s["actor"], s["description"], variant) for s in steps]
    approvals = [is_approval_step(s["name"]) for s in steps]
    roles = [base_role(s["actor"]) for s in steps]
    handoffs = sum(1 for i in range(1, len(steps)) if roles[i] != roles[i - 1])
    h2h = sum(1 for i in range(1, len(steps))
              if roles[i] != roles[i - 1] and classes[i] == HUMAN and classes[i - 1] == HUMAN)
    return {
        "steps": len(steps),
        "HUMAN": classes.count(HUMAN), "HYBRID": classes.count(HYBRID), "AGENT": classes.count(AGENT),
        "HITL": sum(1 for c, a in zip(classes, approvals) if c == HYBRID or a),
        "handoffs": handoffs, "h2h": h2h, "approvals": sum(approvals),
    }


# --- model ---------------------------------------------------------------------


def r_value(cls: str, rh: float, e: float, k: float) -> float:
    return 1.0 if cls == HUMAN else rh if cls == HYBRID else e * k


def m_value(disposition: str, m: float) -> float:
    return 1.0 if disposition in ("retained", "restructured") else m


def pi(carry, t, rh, e, k, m) -> float:
    return 1.0 - sum(w * r_value(c, rh, e, k) * m_value(d, m) for w, (c, d) in zip(t, carry))


def dirichlet_ones(rng: random.Random, n: int) -> list[float]:
    g = [rng.gammavariate(1.0, 1.0) for _ in range(n)]
    total = sum(g)
    return [x / total for x in g]


def quantile(values: list[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default)."""
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for idx in order[i:j + 1]:
            out[idx] = (i + j) / 2 + 1
        i = j + 1
    return out


def residuals(y: list[float], xs: list[list[float]]) -> list[float]:
    """Residuals of y regressed on the columns xs plus an intercept (normal equations)."""
    cols = [[1.0] * len(y)] + xs
    p = len(cols)
    a = [[sum(ci * cj for ci, cj in zip(cols[i], cols[j])) for j in range(p)] for i in range(p)]
    b = [sum(ci * yi for ci, yi in zip(cols[i], y)) for i in range(p)]
    for i in range(p):  # Gauss-Jordan elimination with partial pivoting
        piv = max(range(i, p), key=lambda r: abs(a[r][i]))
        a[i], a[piv], b[i], b[piv] = a[piv], a[i], b[piv], b[i]
        for r in range(p):
            if r != i:
                f = a[r][i] / a[i][i]
                a[r] = [x - f * yv for x, yv in zip(a[r], a[i])]
                b[r] -= f * b[i]
    beta = [b[i] / a[i][i] for i in range(p)]
    return [yi - sum(beta[j] * cols[j][n] for j in range(p)) for n, yi in enumerate(y)]


def corr(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / (sxx * syy) ** 0.5


def prcc(params: dict[str, list[float]], outcome: list[float]) -> dict[str, float]:
    ranked = {k: ranks(v) for k, v in params.items()}
    y = ranks(outcome)
    out = {}
    for k in params:
        others = [ranked[o] for o in params if o != k]
        out[k] = corr(residuals(ranked[k], others), residuals(y, others))
    return out


def pooled(per_workflow: dict[str, float], workflows: list[str]) -> float:
    return median(per_workflow[w] for w in workflows)


def bootstrap(per_workflow: dict[str, float], workflows: list[str], rng: random.Random):
    stats = [median(per_workflow[rng.choice(workflows)] for _ in workflows) for _ in range(BOOTSTRAP)]
    return quantile(stats, 0.05), quantile(stats, 0.95)


# --- main ----------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    encodings, council, tss = load(args.set_name, args.runs_root)
    carry = {v: {r: carried(encodings[wf], tss[r], v) for wf in TEMPLATE_WORKFLOWS for r in council[wf]}
             for v in VARIANTS}

    rng = random.Random(SEED)
    draws = []
    for _ in range(DRAWS):
        draws.append({
            "r_h": rng.triangular(RH[0], RH[2], RH[1]),
            "e_transactional": rng.uniform(*E_RANGE["transactional"]),
            "e_judgment": rng.uniform(*E_RANGE["judgment-dense"]),
            "k": rng.uniform(*K),
            "m": rng.uniform(*M),
            "t": {wf: dirichlet_ones(rng, len(encodings[wf]["steps"])) for wf in TEMPLATE_WORKFLOWS},
        })

    def e_for(d, wf):
        return d["e_transactional"] if SUBGROUP[wf] == "transactional" else d["e_judgment"]

    results = {}
    for v in VARIANTS:
        samples = {wf: [] for wf in TEMPLATE_WORKFLOWS}
        per_draw_pooled = []
        for d in draws:
            wf_means = {}
            for wf in TEMPLATE_WORKFLOWS:
                vals = [pi(carry[v][r], d["t"][wf], d["r_h"], e_for(d, wf), d["k"], d["m"]) for r in council[wf]]
                samples[wf] += vals
                wf_means[wf] = mean(vals)
            per_draw_pooled.append(pooled(wf_means, TEMPLATE_WORKFLOWS))
        wf_median = {wf: median(samples[wf]) for wf in TEMPLATE_WORKFLOWS}
        boot_rng = random.Random(SEED + 1)
        groups = {"all": TEMPLATE_WORKFLOWS,
                  "transactional": [w for w in TEMPLATE_WORKFLOWS if SUBGROUP[w] == "transactional"],
                  "judgment-dense": [w for w in TEMPLATE_WORKFLOWS if SUBGROUP[w] == "judgment-dense"]}
        pooled_stats = {g: (pooled(wf_median, ws), *bootstrap(wf_median, ws, boot_rng)) for g, ws in groups.items()}

        worst = {}
        for wf in TEMPLATE_WORKFLOWS:
            e_max = E_RANGE[SUBGROUP[wf]][1]
            worst[wf] = min(1.0 - max(r_value(c, RH[2], e_max, K[1]) * m_value(dd, 1.0) for c, dd in carry[v][r])
                            for r in council[wf])

        sens = prcc({k: [d[k] for d in draws] for k in ["r_h", "e_transactional", "e_judgment", "k", "m"]},
                    per_draw_pooled)

        def oat(name, value):
            central = {"r_h": RH[1], "e_transactional": mean(E_RANGE["transactional"]),
                       "e_judgment": mean(E_RANGE["judgment-dense"]), "k": mean(K), "m": mean(M)}
            central[name] = value
            means = {}
            for wf in TEMPLATE_WORKFLOWS:
                n = len(encodings[wf]["steps"])
                e = central["e_transactional"] if SUBGROUP[wf] == "transactional" else central["e_judgment"]
                means[wf] = mean(pi(carry[v][r], [1 / n] * n, central["r_h"], e, central["k"], central["m"])
                                 for r in council[wf])
            return pooled(means, TEMPLATE_WORKFLOWS)

        ranges = {"r_h": (RH[0], RH[2]), "e_transactional": E_RANGE["transactional"],
                  "e_judgment": E_RANGE["judgment-dense"], "k": K, "m": M}
        oat_rows = {p: (oat(p, lo), oat(p, hi)) for p, (lo, hi) in ranges.items()}
        results[v] = {
            "wf": {wf: (wf_median[wf], quantile(samples[wf], 0.05), quantile(samples[wf], 0.95))
                   for wf in TEMPLATE_WORKFLOWS},
            "pooled": pooled_stats, "worst": worst, "prcc": sens, "oat": oat_rows,
            "central": oat("m", mean(M)),
        }

    out = []
    add = out.append
    add("# Structural Productivity Potential (exploratory)")
    add("")
    add("**Exploratory, post hoc relative to the pre-registered study.** These are estimates "
        "of the *expected productivity potential under stated assumptions*, built into the "
        "council designs. They are not measured operational outcomes. Method: "
        "`docs/PRODUCTIVITY_METHOD.md` (`a67c2af`). Classification decisions: "
        "`docs/PRODUCTIVITY_DECISIONS.md` (`4ab2958`). Both were committed before computation. "
        "Generated by `scripts/productivity_heldout.py`, whose docstring records "
        "the implementation choices C1 to C10, fixed before the first computation.")
    add("")
    add(f"Seed {SEED} (bootstrap seed {SEED + 1}); {DRAWS:,} Monte Carlo draws; {BOOTSTRAP:,} "
        f"bootstrap resamples; Python {platform.python_version()} `random` (Mersenne Twister). "
        f"33 council runs over 7 held-out workflows. The baseline is excluded (method section 1). "
        f"PI = 1 − H / H_original, where H_original = 1. Primary and agentic-only use the same "
        f"draws.")
    add("")

    for v in VARIANTS:
        label = "Primary classification" if v == PRIMARY else \
            "Declared variant: agentic-only (deterministic automation classed HUMAN)"
        res = results[v]
        add(f"## {label}")
        add("")
        add("### PI per workflow")
        add("")
        add("| Workflow | Subgroup | Runs | Median PI | 90% interval | Worst case (worst run) |")
        add("|---|---|---:|---:|---|---:|")
        for wf in TEMPLATE_WORKFLOWS:
            md_, lo, hi = res["wf"][wf]
            add(f"| {wf} | {SUBGROUP[wf]} | {len(council[wf])} | {md_:.3f} | {lo:.3f} – {hi:.3f} | "
                f"{res['worst'][wf]:.3f} |")
        add("")
        add("### Pooled and subgroups (median of workflow medians, workflow-level bootstrap)")
        add("")
        add("| Group | Workflows | PI | 90% bootstrap interval |")
        add("|---|---:|---:|---|")
        for g, ws in (("all", 7), ("transactional", 4), ("judgment-dense", 3)):
            p, lo, hi = res["pooled"][g]
            add(f"| {g} | {ws} | {p:.3f} | {lo:.3f} – {hi:.3f} |")
        add("")
        add("With only 3 or 4 workflows, a subgroup bootstrap can take only a few distinct "
            "values, so its interval is coarse.")
        add("")
        add("### Sensitivity")
        add("")
        add("| Parameter | PRCC with pooled PI | Rank by abs(PRCC) | OAT pooled PI at min | OAT pooled PI at max |")
        add("|---|---:|---:|---:|---:|")
        order = sorted(res["prcc"], key=lambda p: -abs(res["prcc"][p]))
        for p in order:
            lo, hi = res["oat"][p]
            add(f"| {p} | {res['prcc'][p]:+.3f} | {order.index(p) + 1} | {lo:.3f} | {hi:.3f} |")
        add("")
        add(f"OAT central-values pooled PI (equal step weights): {res['central']:.3f}. The "
            "Dirichlet step weights are not in the PRCC (choice C6).")
        add("")

    add("## Structural counts (no parameters, method section 5)")
    add("")
    add("Original encoding vs council runs, shown as mean (min–max) over the workflow's "
        "council runs. HITL = HYBRID steps + approval steps, each step counted once. "
        "Hand-offs compare base roles.")
    add("")
    keys = [("steps", "Steps"), ("HUMAN", "HUMAN"), ("HYBRID", "HYBRID"), ("AGENT", "AGENT"),
            ("HITL", "HITL checkpoints"), ("handoffs", "Actor hand-offs"),
            ("h2h", "Human-to-human hand-offs"), ("approvals", "Approval steps")]
    for v in VARIANTS:
        add(f"### {'Primary' if v == PRIMARY else 'Agentic-only variant'}")
        add("")
        add("| Workflow | Source | " + " | ".join(lbl for _, lbl in keys) + " |")
        add("|---|---|" + "---:|" * len(keys))
        for wf in TEMPLATE_WORKFLOWS:
            o = structural(encodings[wf]["steps"], v)
            add(f"| {wf} | original | " + " | ".join(str(o[k]) for k, _ in keys) + " |")
            cs = [structural(tss[r]["steps"], v) for r in council[wf]]
            cells = []
            for k, _ in keys:
                vals = [c[k] for c in cs]
                cells.append(f"{mean(vals):.1f} ({min(vals)}–{max(vals)})")
            add(f"| {wf} | council | " + " | ".join(cells) + " |")
        add("")

    add("## Plausibility check (not an input)")
    add("")
    add("Method section 6 names, as a plausibility check only: reported reductions of about "
        "80% in manual effort in deployed AP automation, and of 50% in cost in a "
        "human-in-the-loop case (references as given in the method). They are listed for "
        "comparison and play no part in any figure above.")
    add("")

    args.out.write_text("\n".join(out) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
