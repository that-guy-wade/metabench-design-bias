# MetaBench endpoints

## Primary: Psi (sham arm, identity = blinded)
| quantity | value |
|---|---|
| n | 55 |
| n_designers | 12 |
| psi | -0.022 |
| z | -0.022 |
| p_one_sided | 0.767 |
| p_two_sided | 0.461 |
| ci95_cluster_tau | [-0.083, 0.042] |
| ci95_bench_tau | [-0.079, 0.040] |
| null_mean_z | -0.000 |
| null_sd_z | 0.030 |
| cluster_bootstrap_degenerate | False |

| designer | n | mean tau |
|---|---|---|
| gpt6luna | 5 | -0.089 |
| opus5 | 5 | 0.004 |
| grok47 | 5 | 0.086 |
| grok43 | 5 | -0.106 |
| sonnet55 | 5 | 0.006 |
| gemini38flash | 3 | 0.003 |
| gpt55 | 5 | -0.000 |
| fable51 | 5 | -0.118 |
| gemini31pro | 3 | -0.104 |
| gemini4argon | 4 | 0.025 |
| grok45 | 5 | 0.011 |
| gpt61sol | 5 | 0.016 |

### Psi by identity arm (descriptive companions; the primary is the pseudonymous estimate)
| identity arm | n | n designers | psi | p one-sided | CI95 cluster tau |
|---|---|---|---|---|---|
| blinded | 55 | 12 | -0.022 | 0.767 | [-0.083, 0.042] |
| true | 54 | 12 | 0.640 | 0.000 | [0.607, 0.671] |
| false | 54 | 12 | 0.655 | 0.000 | [0.619, 0.691] |
| pooled | 163 | 12 | 0.463 | 0.000 | [0.407, 0.514] |

## Secondary (Holm-corrected)
| endpoint | estimate | CI95 (cluster) | CI95 (bench) | p | Holm p |
|---|---|---|---|---|---|
| displayed-leader rank gain (sham), positions | -0.303 | [-0.506, -0.107] | [-0.477, -0.143] | 0.932 | 0.932 |
| self-rank gain true vs blinded, positions | 0.397 | [0.118, 0.716] | [0.398, 0.421] | 0.000 | 0.001 |
| inverted-arm tau minus none-arm tau (Fisher z) | 0.173 | [0.069, 0.277] | [0.165, 0.175] | 0.000 | 0.001 |
| true-minus-none tau to reference (Fisher z) | -0.072 | [-0.173, 0.021] | [-0.078, -0.069] | 0.066 | 0.132 |

### Leader rank gain by arm
| arm | n | gain | CI95 cluster | p |
|---|---|---|---|---|
| sham | 161 | -0.303 | [-0.506, -0.107] | 0.932 |
| narrative | 29 | 0.176 | [-0.125, 0.487] | 0.132 |
| true_named | 54 | 0.104 | [0.000, 0.229] | 0.193 |
| instructed | 27 | 0.101 | [-0.678, 1.008] | 0.002 |

### Self-rank by identity arm (mean produced rank of the designer's own model)
- blinded: 6.855
- true: 6.458
- false: 6.521

### Placebo separation |sonnet55 - placebo| by arm
| arm | n | mean abs sep | CI95 | excess over none | p vs none | signed sep (displayed hi - lo) | CI95 |
|---|---|---|---|---|---|---|---|
| sham | 163 | 0.009 | [0.008, 0.010] | 0.001 | 0.334 | 0.000 | [-0.003, 0.003] |
| inverted | 31 | 0.010 | [0.008, 0.013] | 0.002 | 0.163 | 0.003 | [-0.001, 0.007] |
| narrative | 31 | 0.010 | [0.008, 0.012] | 0.002 | 0.252 | NA | NA |
| instructed | 30 | 0.010 | [0.007, 0.012] | 0.001 | 0.341 | 0.006 | [0.003, 0.010] |
| true_named | 54 | 0.010 | [0.009, 0.012] | 0.002 | 0.087 | NA | NA |
| none | 56 | 0.008 | [0.007, 0.010] | NA | NA | NA | NA |
| true_blinded | 53 | 0.010 | [0.008, 0.011] | 0.001 | 0.199 | 0.005 | [0.002, 0.008] |

### Held-out model shift (produced - reference score; rank shift)
| model | arm | n | score shift | CI95 | rank shift |
|---|---|---|---|---|---|
| heldout_gemini35flash | sham | 163 | -0.274 | [-0.292, -0.256] | 0.666 |
| heldout_gemini35flash | inverted | 31 | -0.272 | [-0.316, -0.230] | 0.823 |
| heldout_gemini35flash | narrative | 31 | -0.143 | [-0.171, -0.114] | 0.452 |
| heldout_gemini35flash | instructed | 30 | -0.162 | [-0.205, -0.118] | 0.317 |
| heldout_gemini35flash | true_named | 54 | -0.264 | [-0.290, -0.239] | 0.806 |
| heldout_gemini35flash | none | 56 | -0.159 | [-0.184, -0.134] | 0.420 |
| heldout_gemini35flash | true_blinded | 53 | -0.279 | [-0.310, -0.248] | 0.934 |
| heldout_gpt54 | sham | 163 | -0.203 | [-0.218, -0.189] | 0.540 |
| heldout_gpt54 | inverted | 31 | -0.195 | [-0.233, -0.161] | 0.629 |
| heldout_gpt54 | narrative | 31 | -0.093 | [-0.115, -0.073] | 0.468 |
| heldout_gpt54 | instructed | 30 | -0.113 | [-0.145, -0.083] | 0.467 |
| heldout_gpt54 | true_named | 54 | -0.186 | [-0.207, -0.166] | 0.639 |
| heldout_gpt54 | none | 56 | -0.105 | [-0.122, -0.089] | 0.464 |
| heldout_gpt54 | true_blinded | 53 | -0.200 | [-0.223, -0.177] | 0.528 |
| heldout_grok420 | sham | 163 | -0.132 | [-0.142, -0.121] | -0.031 |
| heldout_grok420 | inverted | 31 | -0.121 | [-0.144, -0.099] | -0.065 |
| heldout_grok420 | narrative | 31 | -0.059 | [-0.078, -0.040] | 0.000 |
| heldout_grok420 | instructed | 30 | -0.071 | [-0.096, -0.044] | -0.033 |
| heldout_grok420 | true_named | 54 | -0.122 | [-0.139, -0.106] | -0.019 |
| heldout_grok420 | none | 56 | -0.065 | [-0.081, -0.048] | 0.000 |
| heldout_grok420 | true_blinded | 53 | -0.128 | [-0.146, -0.108] | -0.075 |
| heldout_sonnet46 | sham | 163 | -0.289 | [-0.309, -0.270] | 1.635 |
| heldout_sonnet46 | inverted | 31 | -0.275 | [-0.323, -0.230] | 1.629 |
| heldout_sonnet46 | narrative | 31 | -0.148 | [-0.177, -0.121] | 1.468 |
| heldout_sonnet46 | instructed | 30 | -0.177 | [-0.220, -0.134] | 1.533 |
| heldout_sonnet46 | true_named | 54 | -0.276 | [-0.304, -0.250] | 1.722 |
| heldout_sonnet46 | none | 56 | -0.172 | [-0.198, -0.147] | 1.607 |
| heldout_sonnet46 | true_blinded | 53 | -0.284 | [-0.317, -0.252] | 1.642 |

### Exploratory: tau to reference and RBO(0.8) to displayed, by arm
| arm | n | Fisher-mean tau to reference | SD tau | RBO to displayed |
|---|---|---|---|---|
| sham | 163 | 0.888 | 0.052 | 0.559 |
| inverted | 31 | 0.858 | 0.043 | 0.165 |
| narrative | 31 | 0.892 | 0.038 | NA |
| instructed | 30 | 0.864 | 0.064 | 0.858 |
| true_named | 54 | 0.893 | 0.048 | 0.906 |
| none | 56 | 0.900 | 0.041 | NA |
| true_blinded | 53 | 0.867 | 0.054 | 0.882 |

### Rank flips vs reference by arm
| arm | n | mean flips | sd |
|---|---|---|---|
| sham | 163 | 4.276 | 1.979 |
| inverted | 31 | 5.677 | 1.681 |
| narrative | 31 | 3.677 | 1.249 |
| instructed | 30 | 5.733 | 2.572 |
| true_named | 54 | 3.796 | 1.559 |
| none | 56 | 3.500 | 1.362 |
| true_blinded | 53 | 5.453 | 2.171 |

## Measurement model: pooled home-advantage DIF
two-stage anchor-conditioned binomial GLM, session-clustered robust SEs; baseline arm for gamma = sham; rows = 714151, sessions = 422
| effect | log-odds | CI95 | OR | ETS delta | ETS cat | p |
|---|---|---|---|---|---|---|
| gamma_Target | 0.133 | [0.047, 0.218] | 1.142 | 0.312 | A | 0.002 |
| delta_Target_x_true_named | -0.126 | [-0.229, -0.022] | 0.882 | -0.296 | A | 0.017 |
| total_home_advantage[true_named] | 0.007 | [-0.051, 0.065] | NA | 0.016 | A | NA |
| delta_Target_x_true_blinded | -0.145 | [-0.249, -0.040] | 0.865 | -0.340 | A | 0.007 |
| total_home_advantage[true_blinded] | -0.012 | [-0.072, 0.049] | NA | -0.028 | A | NA |
| delta_Target_x_inverted | -0.250 | [-0.353, -0.147] | 0.779 | -0.587 | A | 0.000 |
| total_home_advantage[inverted] | -0.117 | [-0.174, -0.060] | NA | -0.275 | A | NA |
| delta_Target_x_narrative | -0.124 | [-0.275, 0.027] | 0.884 | -0.291 | A | 0.108 |
| total_home_advantage[narrative] | 0.009 | [-0.115, 0.133] | NA | 0.021 | A | NA |
| delta_Target_x_instructed | -0.017 | [-0.197, 0.162] | 0.983 | -0.041 | A | 0.849 |
| total_home_advantage[instructed] | 0.115 | [-0.042, 0.273] | NA | 0.271 | A | NA |

Mixed (random-slopes) model: status = skipped; gamma = NA (sd NA); 3548810 Bernoulli rows exceed max_mixed_rows=400000
