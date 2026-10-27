# Sequential single agent vs council vs baseline: P2P-TWM-01

Exploratory, post-freeze. Sequential = one agent, seven cumulative perspectives, seven reconsiderations, synthesis (15 calls).

| Condition | n | Depth (mean) | min | max | Verified depth | Conformance | Runs < 1 | Consistency | Input tok | Output tok | Cost USD | Design words |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 5 | 0.771 | 0.714 | 0.857 | 0.714 | 1.000 | 0 | 0.829 | 7,736 | 5,080 | 0.07 | 440 |
| sequential | 5 | 0.971 | 0.857 | 1.000 | 0.971 | 0.880 | 5 | 0.786 | 402,552 | 61,857 | 1.42 | 951 |
| council | 5 | 0.971 | 0.857 | 1.000 | 0.971 | 0.920 | 4 | 0.829 | 279,271 | 85,264 | 1.41 | 891 |

Gap council minus sequential, depth as recorded: +0.000; verified: +0.000.
Gap sequential minus baseline, depth as recorded: +0.200; verified: +0.257.
Compute ratio sequential/council: input 1.44, output 0.73, cost 1.01.
