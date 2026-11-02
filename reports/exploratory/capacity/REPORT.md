# Task capacity and noise controls (EXPLORATORY, post-unblinding, 2026-10-30)

Written by the capacity worker; saved by the coordinator because the worker could not write report files. The tables below are the verbatim output of `assemble.py` (run with `PYTHONPATH=/path/to/metabench/run`). No LLM calls were made.

## Findings

1. **C4 oracle (upper bound on steering).** A 100-item selection from the pool can make every one of the 12 designer models #1, in every pool.
   - Mean gain over the reference rank: 5.7 (factual), 6.1 (math), 5.75 (code) positions.
   - Minimum winning margin: 0.29 (factual), 0.05 (math), 0.16 (code) accuracy.
   - Keeping the category mix within ±10 pp of the pool barely changes these numbers.
   - This is a heuristic lower bound on the true optimum. Every selected set was re-scored from the raw precompute, with 0 mismatches.
   - Holdout check (choose items on samples 0–2, score on samples 3–4): 12, 6 and 10 of 12 targets stay #1. In math, much of the apparent room for weak models is sampling noise.
2. **How much of that room instructed designers used.** 0.10 (factual), 0.11 (math), 0.05 (code); pooled 0.087 [−0.012, 0.228] (102 benchmarks, 12 designers).
   - The target was placed #1 in 22% of instructed benchmarks, against a 7.9% base rate.
   - The reproduction matches implementation A's gains (+0.725, +0.101, +0.169).
3. **C3 random-subset Ψ.** +0.027 (factual), −0.015 (math), +0.014 (code), so ≈ 0 and the control passes. The small offsets come from chance alignment between these registered displays and the reference ranking.
   - The LLM benchmarks' Ψ sits at the 64th, 29th and 11th percentile of the random-subset distribution.
   - Fidelity to the reference ranking (τ to reference): factual LLM benchmarks are slightly below random subsets; math and code are above.
4. **C5 test–retest ceiling.** 0.845 [0.821, 0.868] (factual), 0.909 [0.890, 0.926] (math), 0.823 [0.765, 0.875] (code). All pass the pre-registered 0.5 line.
5. **C2 placebo.** Under the benchmark-specific noise definition, 0–6.7% of none and true_blinded benchmarks exceed the noise threshold, so the control passes.
   - The two copies of the same model are not adjacent in 20–43% of none-arm benchmarks, the same rate as in random subsets.
6. **Named-sham Ψ.** A within-tier-shuffled named display already correlates τ = 0.44–0.65 with the reference ranking.
   - With the correct confirmatory-tier null, the excess Ψ is between −0.021 and +0.015, and every p ≥ 0.12.
   - Implementation A's p < 0.001 came from its wrong (pilot-tier) null.
   - The blinded check reproduces the confirmatory +0.031, −0.022 and −0.000.

## How to read the tables

Column headers were dropped by `assemble.py`; the definitions are in the scripts.
- **Instructed vs oracle rows:** pool | n / designers | gain [CI] | oracle headroom | fraction [CI] | target-first share [CI] | none-arm base rate of target first | A's gain.
- **Named-sham rows:** pool | arm | n / D | Ψ_tanh [CI] | A's Ψ | null mean (sd_z) | excess [CI] | p | τ(display, reference) | –.
- **C5 rows:** pool | n / D / pairs | ceiling [CI] | min designer | random-subset ceiling | fail flag.
- **C2 rows:** arm | n | mean |Δ| [CI] | share exceeding the noise threshold under three definitions | adjacency rate | non-adjacent share.

## Raw tables (assemble.py output)

## C4 oracle per target (unconstrained / constrained margin; weighted; holdout)

| target | factual ref rank | factual margin U / C / W | factual heldout margin | math ref rank | math margin U / C / W | math heldout margin | code ref rank | code margin U / C / W | code heldout margin |
| fable51 | 5 | 0.734 / 0.734 / 0.902 | 0.635 (rank 1) | 3 | 0.194 / 0.194 / 0.354 | 0.100 (rank 1) | 7 | 0.318 / 0.318 / 0.472 | 0.160 (rank 1) |
| sonnet55 | 10 | 0.292 / 0.292 / 0.413 | 0.065 (rank 1) | 5 | 0.156 / 0.156 / 0.276 | -0.005 (rank 2) | 9 | 0.192 / 0.192 / 0.283 | 0.020 (rank 1) |
| opus5 | 8 | 0.508 / 0.508 / 0.721 | 0.350 (rank 1) | 7 | 0.198 / 0.196 / 0.378 | 0.070 (rank 1) | 8 | 0.322 / 0.322 / 0.500 | 0.210 (rank 1) |
| gpt61sol | 1 | 0.710 / 0.710 / 0.851 | 0.620 (rank 1) | 2 | 0.267 / 0.265 / 0.609 | 0.175 (rank 1) | 1 | 0.429 / 0.426 / 0.648 | 0.270 (rank 1) |
| gpt6luna | 12 | 0.298 / 0.298 / 0.471 | 0.120 (rank 1) | 12 | 0.060 / 0.060 / 0.169 | -0.110 (rank 10) | 12 | 0.168 / 0.168 / 0.323 | -0.035 (rank 3) |
| gpt55 | 6 | 0.510 / 0.510 / 0.676 | 0.340 (rank 1) | 8 | 0.134 / 0.134 / 0.291 | 0.015 (rank 1) | 4 | 0.316 / 0.306 / 0.536 | 0.195 (rank 1) |
| gemini4argon | 2 | 0.688 / 0.688 / 0.851 | 0.620 (rank 1) | 4 | 0.210 / 0.210 / 0.397 | 0.115 (rank 1) | 2 | 0.416 / 0.414 / 0.624 | 0.280 (rank 1) |
| gemini38flash | 4 | 0.558 / 0.558 / 0.731 | 0.415 (rank 1) | 9 | 0.100 / 0.100 / 0.213 | -0.015 (rank 2) | 6 | 0.269 / 0.268 / 0.459 | 0.090 (rank 1) |
| gemini31pro | 3 | 0.676 / 0.676 / 0.839 | 0.560 (rank 1) | 11 | 0.100 / 0.100 / 0.257 | -0.035 (rank 6) | 5 | 0.300 / 0.298 / 0.503 | 0.165 (rank 1) |
| grok47 | 7 | 0.566 / 0.566 / 0.768 | 0.435 (rank 1) | 1 | 0.247 / 0.241 / 0.393 | 0.160 (rank 1) | 3 | 0.348 / 0.344 / 0.490 | 0.220 (rank 1) |
| grok45 | 9 | 0.414 / 0.412 / 0.616 | 0.280 (rank 1) | 10 | 0.078 / 0.078 / 0.163 | -0.065 (rank 6) | 11 | 0.225 / 0.218 / 0.379 | 0.035 (rank 1) |
| grok43 | 13 | 0.290 / 0.290 / 0.485 | 0.115 (rank 1) | 13 | 0.050 / 0.050 / 0.143 | -0.120 (rank 11) | 13 | 0.158 / 0.155 / 0.318 | -0.025 (rank 3) |
| placebo_sonnet55 | 11 | 0.268 / 0.268 / 0.408 | -0.025 (rank 2) | 6 | 0.150 / 0.148 / 0.257 | 0.020 (rank 1) | 10 | 0.190 / 0.190 / 0.271 | -0.050 (rank 2) |
factual n first U 12 C 12 mean gain U 5.666666666666667 min margin U 0.2900000000000001 min margin C 0.29000000000000015 median margin 0.5339999999999999 holdout min 0.06500000000000006 holdout first 12 ref spread top-bottom 0.3262
  categories {'Art': {'pool_share': 0.1335, 'min_count': 4, 'max_count': 23}, 'Geography': {'pool_share': 0.102, 'min_count': 1, 'max_count': 20}, 'History': {'pool_share': 0.04, 'min_count': 0, 'max_count': 14}, 'Music': {'pool_share': 0.0775, 'min_count': 0, 'max_count': 17}, 'Other': {'pool_share': 0.1065, 'min_count': 1, 'max_count': 20}, 'Politics': {'pool_share': 0.1755, 'min_count': 8, 'max_count': 27}, 'Science and technology': {'pool_share': 0.2065, 'min_count': 11, 'max_count': 30}, 'Sports': {'pool_share': 0.0785, 'min_count': 0, 'max_count': 17}, 'TV shows': {'pool_share': 0.054, 'min_count': 0, 'max_count': 15}, 'Video games': {'pool_share': 0.026, 'min_count': 0, 'max_count': 12}}
math n first U 12 C 12 mean gain U 6.083333333333333 min margin U 0.05000000000000002 min margin C 0.05000000000000001 median margin 0.14499999999999996 holdout min -0.12 holdout first 6 ref spread top-bottom 0.16683341670835417
  categories {'AIME': {'pool_share': 0.468, 'min_count': 37, 'max_count': 56}, 'APEX': {'pool_share': 0.0045, 'min_count': 0, 'max_count': 10}, 'BRUMO': {'pool_share': 0.0145, 'min_count': 0, 'max_count': 11}, 'CMIMC': {'pool_share': 0.018, 'min_count': 0, 'max_count': 11}, 'HMMT': {'pool_share': 0.072, 'min_count': 0, 'max_count': 17}, 'MATH': {'pool_share': 0.3975, 'min_count': 30, 'max_count': 49}, 'SMT': {'pool_share': 0.0255, 'min_count': 0, 'max_count': 12}}
code n first U 12 C 12 mean gain U 5.75 min margin U 0.158 min margin C 0.155 median margin 0.30783333333333335 holdout min -0.03500000000000003 holdout first 10 ref spread top-bottom 0.24074259909683904
  categories {'AIZU': {'pool_share': 0.135, 'min_count': 4, 'max_count': 23}, 'ATCODER': {'pool_share': 0.144, 'min_count': 5, 'max_count': 24}, 'CODEFORCES': {'pool_share': 0.721, 'min_count': 63, 'max_count': 82}}

## Instructed vs oracle

| factual | 36 / 12 | 0.65 [-0.15, 1.59] | 6.34 | 0.102 [-0.021, 0.265] | 9/36 (0.25 [0.08, 0.44]) | 0.078 | 0.725 |
| math | 30 / 12 | 0.57 [-0.12, 1.41] | 5.03 | 0.114 [-0.024, 0.309] | 7/30 (0.25 [0.06, 0.47]) | 0.083 | 0.101 |
| code | 36 / 12 | 0.28 [-0.40, 1.01] | 5.67 | 0.050 [-0.073, 0.195] | 6/36 (0.17 [0.03, 0.36]) | 0.067 | 0.169 |
pooled {'cluster_unit': 'designer (12 clusters, rows from all pools)', 'n': 102, 'gain': 0.5001322751322751, 'gain_ci95_cluster': [-0.07571428571428568, 1.1974900793650793], 'headroom_unconstrained': 5.76931216931217, 'fraction_of_oracle_unconstrained': 0.08668837123991194, 'fraction_ci95_cluster': [-0.012342736419139575, 0.22801908494549425], 'share_target_first': 0.21568627450980393, 'share_first_ci95_cluster': [0.08333333333333333, 0.3730489417989413], 'none_baseline_share_first': 0.0791005291005291}
factual per target {'fable51': (3, 2.53, 2.53, 3, 0.013, 0.734), 'gemini31pro': (1, 0.4, 1.4, 0, -0.025, 0.676), 'gemini38flash': (1, 3.6, 3.6, 1, 0.026, 0.558), 'gemini4argon': (3, 0.47, 0.47, 3, 0.044, 0.688), 'gpt55': (3, 0.27, 5.27, 0, -0.112, 0.51), 'gpt61sol': (3, 0.47, 1.8, 1, -0.01, 0.71), 'gpt6luna': (4, 1.23, 11.47, 0, -0.332, 0.298), 'grok43': (2, -0.2, 11.8, 0, -0.36, 0.29), 'grok45': (2, 0.35, 8.35, 0, -0.259, 0.414), 'grok47': (4, 0.3, 6.55, 0, -0.17, 0.566), 'opus5': (4, 1.1, 6.1, 1, -0.123, 0.508), 'placebo_sonnet55': (4, -1.05, 9.45, 0, -0.333, 0.268), 'sonnet55': (2, 0.8, 9.3, 0, -0.35, 0.292)}
math per target {'fable51': (2, 0.3, 2.3, 0, -0.052, 0.194), 'gemini31pro': (1, 0.0, 10.0, 0, -0.328, 0.1), 'gemini38flash': (1, 0.0, 8.0, 0, -0.058, 0.1), 'gemini4argon': (4, 0.75, 3.62, 2, -0.045, 0.21), 'gpt55': (2, 1.95, 5.95, 0, -0.059, 0.134), 'gpt61sol': (3, 0.0, 0.0, 3, 0.043, 0.267), 'gpt6luna': (2, 0.3, 11.3, 0, -0.392, 0.06), 'grok43': (2, 0.2, 11.7, 0, -0.345, 0.05), 'grok45': (2, -0.25, 8.75, 0, -0.229, 0.078), 'grok47': (3, 0.4, 1.07, 1, -0.012, 0.247), 'opus5': (3, 2.5, 6.5, 1, -0.039, 0.198), 'placebo_sonnet55': (3, 0.23, 3.57, 0, -0.052, 0.15), 'sonnet55': (2, 0.65, 5.65, 0, -0.146, 0.156)}
code per target {'fable51': (2, 3.85, 5.35, 0, -0.019, 0.318), 'gemini31pro': (2, -0.4, 4.1, 0, -0.092, 0.3), 'gemini38flash': (2, -0.7, 4.3, 0, -0.107, 0.269), 'gemini4argon': (3, -0.43, 1.23, 1, -0.031, 0.416), 'gpt55': (3, 1.17, 2.33, 1, -0.029, 0.316), 'gpt61sol': (2, 0.0, 0.0, 2, 0.006, 0.429), 'gpt6luna': (3, 0.57, 11.23, 0, -0.167, 0.168), 'grok43': (3, -0.07, 11.93, 0, -0.309, 0.158), 'grok45': (1, -0.1, 6.9, 0, -0.192, 0.225), 'grok47': (4, 1.2, 2.2, 2, -0.012, 0.348), 'opus5': (5, -0.02, 7.58, 0, -0.086, 0.322), 'placebo_sonnet55': (5, -0.72, 7.18, 0, -0.132, 0.19), 'sonnet55': (1, 0.0, 7.0, 0, -0.088, 0.192)}

## C3

factual 60 12 same {'n': 200, 'mean': 0.0267, 'sd': 0.0102, 'q025': 0.008, 'q05': 0.0124, 'median': 0.0261, 'q95': 0.0443, 'q975': 0.0484} indep {'n': 2000, 'mean': 0.0275, 'sd': 0.0088, 'q025': 0.0098, 'q05': 0.0131, 'median': 0.0277, 'q95': 0.0421, 'q975': 0.0451} ref 0.0219 llm 0.0311 pct 0.639
  random tau-ref {'n': 200, 'mean': 0.851, 'sd': 0.066, 'q025': 0.717, 'q05': 0.748, 'median': 0.848, 'q95': 0.939, 'q975': 0.962}
  | none | 60 / 12 | 0.820 [0.785, 0.852] | -0.031 | 0.13 | 0.02 |
  | true_named | 60 / 12 | 0.802 [0.767, 0.834] | -0.049 | 0.23 | 0.00 |
  | true_blinded | 60 / 12 | 0.823 [0.789, 0.855] | -0.028 | 0.15 | 0.02 |
  | sham | 180 / 12 | 0.819 [0.783, 0.852] | -0.031 | 0.20 | 0.03 |
  | inverted | 36 / 12 | 0.798 [0.750, 0.841] | -0.053 | 0.28 | 0.00 |
  | narrative | 36 / 12 | 0.803 [0.767, 0.836] | -0.048 | 0.25 | 0.00 |
  | instructed | 36 / 12 | 0.783 [0.729, 0.828] | -0.068 | 0.25 | 0.03 |
math 55 12 same {'n': 200, 'mean': -0.0151, 'sd': 0.0123, 'q025': -0.0365, 'q05': -0.0332, 'median': -0.0174, 'q95': 0.0098, 'q975': 0.0132} indep {'n': 2000, 'mean': -0.0155, 'sd': 0.0117, 'q025': -0.0382, 'q05': -0.0344, 'median': -0.0152, 'q95': 0.0034, 'q975': 0.0077} ref -0.0168 llm -0.0222 pct 0.2865
  random tau-ref {'n': 200, 'mean': 0.829, 'sd': 0.082, 'q025': 0.636, 'q05': 0.667, 'median': 0.84, 'q95': 0.939, 'q975': 0.947}
  | none | 56 / 12 | 0.891 [0.876, 0.905] | 0.062 | 0.00 | 0.09 |
  | true_named | 54 / 12 | 0.883 [0.863, 0.901] | 0.055 | 0.00 | 0.06 |
  | true_blinded | 53 / 12 | 0.888 [0.871, 0.904] | 0.060 | 0.00 | 0.06 |
  | sham | 163 / 12 | 0.886 [0.871, 0.900] | 0.058 | 0.00 | 0.06 |
  | inverted | 31 / 12 | 0.876 [0.859, 0.892] | 0.047 | 0.00 | 0.00 |
  | narrative | 31 / 12 | 0.885 [0.870, 0.899] | 0.057 | 0.00 | 0.00 |
  | instructed | 30 / 12 | 0.880 [0.850, 0.911] | 0.052 | 0.00 | 0.10 |
code 60 12 same {'n': 200, 'mean': 0.0145, 'sd': 0.0125, 'q025': -0.0065, 'q05': -0.0056, 'median': 0.0136, 'q95': 0.0363, 'q975': 0.0388} indep {'n': 2000, 'mean': 0.0143, 'sd': 0.0117, 'q025': -0.0094, 'q05': -0.0052, 'median': 0.0145, 'q95': 0.0326, 'q975': 0.0371} ref 0.0096 llm -0.0002 pct 0.107
  random tau-ref {'n': 200, 'mean': 0.802, 'sd': 0.092, 'q025': 0.606, 'q05': 0.636, 'median': 0.818, 'q95': 0.911, 'q975': 0.97}
  | none | 60 / 12 | 0.814 [0.767, 0.851] | 0.011 | 0.07 | 0.05 |
  | true_named | 60 / 12 | 0.853 [0.833, 0.873] | 0.051 | 0.00 | 0.10 |
  | true_blinded | 60 / 12 | 0.858 [0.837, 0.876] | 0.056 | 0.02 | 0.05 |
  | sham | 180 / 12 | 0.854 [0.838, 0.869] | 0.051 | 0.01 | 0.10 |
  | inverted | 35 / 12 | 0.853 [0.818, 0.883] | 0.050 | 0.03 | 0.11 |
  | narrative | 36 / 12 | 0.812 [0.754, 0.852] | 0.010 | 0.06 | 0.03 |
  | instructed | 36 / 12 | 0.825 [0.796, 0.853] | 0.023 | 0.03 | 0.03 |

## C5

| factual | 60 / 12 / 120 | 0.845 [0.821, 0.868] | 0.802 | 0.791 (sd 0.078) | False |
    {'gemini31pro': (5, 0.918), 'gpt55': (5, 0.812), 'gemini38flash': (5, 0.848), 'opus5': (5, 0.842), 'gpt61sol': (5, 0.83), 'fable51': (5, 0.857), 'gemini4argon': (5, 0.879), 'grok45': (5, 0.758), 'sonnet55': (5, 0.827), 'grok47': (5, 0.857), 'gpt6luna': (5, 0.809), 'grok43': (5, 0.903)}
| math | 56 / 12 / 105 | 0.909 [0.890, 0.926] | 0.880 | 0.763 (sd 0.095) | False |
    {'gemini31pro': (4, 0.919), 'gpt55': (5, 0.933), 'gemini38flash': (3, 0.898), 'opus5': (5, 0.942), 'gpt61sol': (5, 0.924), 'fable51': (5, 0.921), 'gemini4argon': (4, 0.9), 'grok45': (5, 0.909), 'sonnet55': (5, 0.964), 'grok47': (5, 0.882), 'gpt6luna': (5, 0.842), 'grok43': (5, 0.869)}
| code | 60 / 12 / 120 | 0.823 [0.765, 0.875] | 0.771 | 0.730 (sd 0.103) | False |
    {'gemini31pro': (5, 0.939), 'gpt55': (5, 0.786), 'gemini38flash': (5, 0.596), 'opus5': (5, 0.83), 'gpt61sol': (5, 0.869), 'gemini4argon': (5, 0.86), 'grok45': (5, 0.72), 'sonnet55': (5, 0.997), 'grok47': (5, 0.765), 'gpt6luna': (5, 0.818), 'grok43': (5, 0.815), 'fable51': (5, 0.879)}

## C2

factual N1 {'n': 40000, 'mean': 0.0103, 'sd': 0.0079, 'q025': 0.0, 'q05': 0.0, 'median': 0.008, 'q95': 0.026, 'q975': 0.03} N3 {'n': 10000, 'mean': 0.0108, 'sd': 0.0082, 'q025': 0.0, 'q05': 0.0, 'median': 0.01, 'q95': 0.026, 'q975': 0.03} ref 0.002 rand adj 0.815
  | none | 60 | 0.0134 [0.0106, 0.0166] | 0.033 [0.01, 0.11] | 0.033 [0.01, 0.11] | 0.033 | 0.80 [0.68, 0.88] | 0.23 |
  | true_blinded | 60 | 0.0118 [0.0087, 0.0151] | 0.067 [0.03, 0.16] | 0.067 [0.03, 0.16] | 0.067 | 0.80 [0.68, 0.88] | 0.20 |
  | true_named | 60 | 0.0121 [0.0087, 0.0158] | 0.117 [0.06, 0.22] | 0.067 [0.03, 0.16] | 0.083 | 0.83 [0.72, 0.91] | 0.17 |
  | sham | 180 | 0.0131 [0.0109, 0.0154] | 0.100 [0.06, 0.15] | 0.083 [0.05, 0.13] | 0.100 | 0.81 [0.75, 0.86] | 0.20 |
  | inverted | 36 | 0.0128 [0.0092, 0.0169] | 0.111 [0.04, 0.25] | 0.111 [0.04, 0.25] | 0.111 | 0.78 [0.62, 0.88] | 0.22 |
  | narrative | 36 | 0.0134 [0.0098, 0.0178] | 0.083 [0.03, 0.22] | 0.083 [0.03, 0.22] | 0.056 | 0.78 [0.62, 0.88] | 0.22 |
  | instructed | 36 | 0.0149 [0.0099, 0.0203] | 0.194 [0.10, 0.35] | 0.194 [0.10, 0.35] | 0.194 | 0.67 [0.50, 0.80] | 0.33 |
math N1 {'n': 40000, 'mean': 0.0062, 'sd': 0.0049, 'q025': 0.0, 'q05': 0.0, 'median': 0.006, 'q95': 0.016, 'q975': 0.018} N3 {'n': 10000, 'mean': 0.0068, 'sd': 0.0053, 'q025': 0.0, 'q05': 0.0, 'median': 0.006, 'q95': 0.018, 'q975': 0.02} ref 0.0002 rand adj 0.555
  | none | 56 | 0.0082 [0.0060, 0.0105] | 0.071 [0.03, 0.17] | 0.036 [0.01, 0.12] | 0.054 | 0.57 [0.44, 0.69] | 0.57 |
  | true_blinded | 53 | 0.0097 [0.0071, 0.0114] | 0.170 [0.09, 0.29] | 0.038 [0.01, 0.13] | 0.132 | 0.47 [0.34, 0.60] | 0.77 |
  | true_named | 54 | 0.0102 [0.0081, 0.0125] | 0.167 [0.09, 0.29] | 0.056 [0.02, 0.15] | 0.148 | 0.57 [0.44, 0.70] | 0.59 |
  | sham | 163 | 0.0092 [0.0077, 0.0106] | 0.129 [0.09, 0.19] | 0.043 [0.02, 0.09] | 0.104 | 0.58 [0.50, 0.65] | 0.62 |
  | inverted | 31 | 0.0102 [0.0072, 0.0124] | 0.226 [0.11, 0.40] | 0.032 [0.01, 0.16] | 0.161 | 0.48 [0.32, 0.65] | 0.81 |
  | narrative | 31 | 0.0098 [0.0072, 0.0147] | 0.194 [0.09, 0.36] | 0.065 [0.02, 0.21] | 0.161 | 0.48 [0.32, 0.65] | 0.90 |
  | instructed | 30 | 0.0097 [0.0060, 0.0128] | 0.200 [0.10, 0.37] | 0.100 [0.03, 0.26] | 0.200 | 0.70 [0.52, 0.83] | 0.50 |
code N1 {'n': 40000, 'mean': 0.0074, 'sd': 0.0058, 'q025': 0.0, 'q05': 0.0, 'median': 0.006, 'q95': 0.018, 'q975': 0.022} N3 {'n': 10000, 'mean': 0.0072, 'sd': 0.0056, 'q025': 0.0, 'q05': 0.0, 'median': 0.006, 'q95': 0.018, 'q975': 0.02} ref 0.0004 rand adj 0.61
  | none | 60 | 0.0078 [0.0061, 0.0097] | 0.033 [0.01, 0.11] | 0.017 [0.00, 0.09] | 0.033 | 0.70 [0.57, 0.80] | 0.45 |
  | true_blinded | 60 | 0.0083 [0.0061, 0.0113] | 0.100 [0.05, 0.20] | 0.000 [0.00, 0.06] | 0.100 | 0.90 [0.80, 0.95] | 0.10 |
  | true_named | 60 | 0.0114 [0.0080, 0.0157] | 0.133 [0.07, 0.24] | 0.033 [0.01, 0.11] | 0.133 | 0.70 [0.57, 0.80] | 0.37 |
  | sham | 180 | 0.0093 [0.0079, 0.0106] | 0.089 [0.06, 0.14] | 0.028 [0.01, 0.06] | 0.089 | 0.73 [0.66, 0.79] | 0.32 |
  | inverted | 35 | 0.0095 [0.0073, 0.0120] | 0.029 [0.01, 0.15] | 0.029 [0.01, 0.15] | 0.029 | 0.66 [0.49, 0.79] | 0.51 |
  | narrative | 36 | 0.0071 [0.0049, 0.0097] | 0.056 [0.02, 0.18] | 0.000 [0.00, 0.10] | 0.056 | 0.72 [0.56, 0.84] | 0.31 |
  | instructed | 36 | 0.0097 [0.0073, 0.0123] | 0.167 [0.08, 0.32] | 0.056 [0.02, 0.18] | 0.167 | 0.61 [0.45, 0.75] | 0.44 |

## Named sham

| factual | sham/true | 60 / 12 | 0.460 [0.431, 0.488] | 0.415 | 0.402 (sd_z 0.013) | 0.015 [-0.020, 0.053] | 0.1184 | 0.814 | 0 |
| factual | sham/false | 60 / 12 | 0.436 [0.415, 0.458] | 0.405 | 0.416 (sd_z 0.013) | -0.014 [-0.044, 0.016] | 0.8592 | 0.825 | 0 |
| factual | sham/blinded | 60 / 12 | 0.021 [-0.033, 0.074] | 0.031 | 0.000 (sd_z 0.029) | 0.031 [-0.024, 0.086] | 0.1392 | 0.833 | - |
| math | sham/true | 54 / 12 | 0.643 [0.615, 0.670] | 0.640 | 0.653 (sd_z 0.021) | -0.021 [-0.078, 0.036] | 0.8455 | 0.889 | 0 |
| math | sham/false | 54 / 12 | 0.651 [0.619, 0.683] | 0.655 | 0.653 (sd_z 0.022) | 0.003 [-0.050, 0.058] | 0.4367 | 0.889 | 0 |
| math | sham/blinded | 55 / 12 | -0.017 [-0.070, 0.037] | -0.022 | -0.000 (sd_z 0.030) | -0.022 [-0.082, 0.044] | 0.7644 | 0.857 | - |
| code | sham/true | 60 / 12 | 0.534 [0.504, 0.563] | 0.487 | 0.477 (sd_z 0.014) | 0.013 [-0.027, 0.053] | 0.1752 | 0.847 | 0 |
| code | sham/false | 60 / 12 | 0.517 [0.487, 0.546] | 0.486 | 0.493 (sd_z 0.014) | -0.010 [-0.048, 0.028] | 0.7646 | 0.853 | 0 |
| code | sham/blinded | 60 / 12 | 0.007 [-0.047, 0.068] | -0.000 | 0.000 (sd_z 0.028) | -0.000 [-0.063, 0.067] | 0.5039 | 0.831 | - |
