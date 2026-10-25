# Bootstrap of the H2 decision rule (held-out set)

10000 replicates, seed 20261025; runs resampled with replacement within each cell; rule: gap >= 0.2 on >= 4 of 7 workflows.

## depth as recorded

Point estimate: 4 of 7 workflows pass; H2 supported.
Bootstrap: H2 passes in 28.5% of replicates.
Leave-one-run-out: H2 passes in 79.4% of the 68 single-run deletions (14 deletions make it fail).

| Workflow | Gap (point) | 95% interval | P(gap >= 0.2) |
|---|---:|---:|---:|
| FPA-ABB-01 | 0.200 | [0.067, 0.311] | 0.57 |
| FPA-VAR-01 | 0.350 | [0.200, 0.500] | 0.98 |
| P2P-EXR-01 | 0.050 | [-0.050, 0.150] | 0.01 |
| P2P-PRE-01 | 0.150 | [0.125, 0.200] | 0.06 |
| P2P-TWM-01 | 0.200 | [0.114, 0.286] | 0.65 |
| R2R-ACR-01 | 0.075 | [-0.050, 0.200] | 0.04 |
| R2R-FSP-01 | 0.222 | [0.089, 0.356] | 0.68 |

Distribution of the number of passing workflows: 0: 0.1%, 1: 4.8%, 2: 24.2%, 3: 42.3%, 4: 25.7%, 5: 2.7%, 6: 0.1%

Cells in which deleting a single run makes H2 fail (number of such runs): FPA-ABB-01 baseline (3); FPA-ABB-01 council (2); P2P-TWM-01 baseline (3); P2P-TWM-01 council (4); R2R-FSP-01 baseline (1); R2R-FSP-01 council (1)

## verified depth

Point estimate: 4 of 7 workflows pass; H2 supported.
Bootstrap: H2 passes in 64.2% of replicates.
Leave-one-run-out: H2 passes in 95.6% of the 68 single-run deletions (3 deletions make it fail).

| Workflow | Gap (point) | 95% interval | P(gap >= 0.2) |
|---|---:|---:|---:|
| FPA-ABB-01 | 0.467 | [0.289, 0.622] | 1.00 |
| FPA-VAR-01 | 0.375 | [0.200, 0.525] | 0.98 |
| P2P-EXR-01 | 0.069 | [-0.037, 0.169] | 0.01 |
| P2P-PRE-01 | 0.200 | [0.150, 0.250] | 0.68 |
| P2P-TWM-01 | 0.257 | [0.171, 0.343] | 0.93 |
| R2R-ACR-01 | -0.050 | [-0.200, 0.100] | 0.00 |
| R2R-FSP-01 | 0.044 | [-0.111, 0.222] | 0.05 |

Distribution of the number of passing workflows: 1: 0.1%, 2: 3.1%, 3: 32.7%, 4: 60.6%, 5: 3.5%, 6: 0.1%

Cells in which deleting a single run makes H2 fail (number of such runs): P2P-PRE-01 baseline (3)

