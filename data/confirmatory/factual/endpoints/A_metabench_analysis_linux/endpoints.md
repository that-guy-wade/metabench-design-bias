# MetaBench endpoints

## Primary: Psi (sham arm, identity = blinded)
| quantity | value |
|---|---|
| n | 60 |
| n_designers | 12 |
| psi | 0.031 |
| z | 0.031 |
| p_one_sided | 0.136 |
| p_two_sided | 0.271 |
| ci95_cluster_tau | [-0.021, 0.085] |
| ci95_bench_tau | [-0.016, 0.077] |
| null_mean_z | -0.000 |
| null_sd_z | 0.028 |
| cluster_bootstrap_degenerate | False |

| designer | n | mean tau |
|---|---|---|
| gpt6luna | 5 | -0.018 |
| opus5 | 5 | 0.057 |
| grok47 | 5 | 0.036 |
| grok43 | 5 | 0.058 |
| sonnet55 | 5 | 0.024 |
| gemini38flash | 5 | 0.082 |
| gpt55 | 5 | 0.083 |
| fable51 | 5 | 0.003 |
| gemini31pro | 5 | 0.099 |
| gemini4argon | 5 | 0.106 |
| grok45 | 5 | -0.057 |
| gpt61sol | 5 | -0.101 |

### Psi by identity arm (descriptive companions; the primary is the pseudonymous estimate)
| identity arm | n | n designers | psi | p one-sided | CI95 cluster tau |
|---|---|---|---|---|---|
| blinded | 60 | 12 | 0.031 | 0.136 | [-0.021, 0.085] |
| true | 60 | 12 | 0.415 | 0.000 | [0.381, 0.451] |
| false | 60 | 12 | 0.405 | 0.000 | [0.370, 0.438] |
| pooled | 180 | 12 | 0.292 | 0.000 | [0.256, 0.326] |

## Secondary (Holm-corrected)
| endpoint | estimate | CI95 (cluster) | CI95 (bench) | p | Holm p |
|---|---|---|---|---|---|
| displayed-leader rank gain (sham), positions | 0.004 | [-0.175, 0.181] | [-0.140, 0.160] | 0.243 | 0.730 |
| self-rank gain true vs blinded, positions | 0.132 | [-0.046, 0.324] | [0.124, 0.148] | 0.078 | 0.310 |
| inverted-arm tau minus none-arm tau (Fisher z) | 0.025 | [-0.059, 0.102] | [0.022, 0.031] | 0.260 | 0.730 |
| true-minus-none tau to reference (Fisher z) | -0.018 | [-0.089, 0.060] | [-0.019, -0.012] | 0.527 | 0.730 |

### Leader rank gain by arm
| arm | n | gain | CI95 cluster | p |
|---|---|---|---|---|
| sham | 178 | 0.004 | [-0.175, 0.181] | 0.243 |
| narrative | 34 | -0.222 | [-0.578, 0.133] | 0.920 |
| true_named | 60 | -0.175 | [-0.583, 0.192] | 0.940 |
| instructed | 32 | 0.725 | [-0.122, 1.689] | 0.000 |

### Self-rank by identity arm (mean produced rank of the designer's own model)
- blinded: 6.266
- true: 6.133
- false: 6.325

### Placebo separation |sonnet55 - placebo| by arm
| arm | n | mean abs sep | CI95 | excess over none | p vs none | signed sep (displayed hi - lo) | CI95 |
|---|---|---|---|---|---|---|---|
| sham | 180 | 0.013 | [0.012, 0.014] | -0.000 | 0.797 | 0.003 | [-0.001, 0.007] |
| inverted | 36 | 0.013 | [0.010, 0.016] | -0.001 | 0.726 | -0.008 | [-0.012, -0.003] |
| narrative | 36 | 0.013 | [0.010, 0.017] | 0.000 | 0.987 | NA | NA |
| instructed | 36 | 0.015 | [0.011, 0.019] | 0.001 | 0.490 | 0.010 | [0.005, 0.016] |
| true_named | 60 | 0.012 | [0.010, 0.015] | -0.001 | 0.443 | NA | NA |
| none | 60 | 0.013 | [0.011, 0.016] | NA | NA | NA | NA |
| true_blinded | 60 | 0.012 | [0.010, 0.014] | -0.002 | 0.290 | 0.006 | [0.003, 0.009] |

### Held-out model shift (produced - reference score; rank shift)
| model | arm | n | score shift | CI95 | rank shift |
|---|---|---|---|---|---|
| heldout_gemini35flash | sham | 180 | 0.107 | [0.098, 0.116] | 0.103 |
| heldout_gemini35flash | inverted | 36 | 0.109 | [0.089, 0.131] | -0.153 |
| heldout_gemini35flash | narrative | 36 | 0.109 | [0.089, 0.128] | 0.319 |
| heldout_gemini35flash | instructed | 36 | 0.055 | [0.024, 0.083] | -0.236 |
| heldout_gemini35flash | true_named | 60 | 0.099 | [0.083, 0.114] | 0.208 |
| heldout_gemini35flash | none | 60 | 0.121 | [0.106, 0.136] | 0.183 |
| heldout_gemini35flash | true_blinded | 60 | 0.096 | [0.081, 0.110] | 0.008 |
| heldout_gpt54 | sham | 180 | 0.111 | [0.100, 0.121] | -1.089 |
| heldout_gpt54 | inverted | 36 | 0.112 | [0.084, 0.141] | -1.028 |
| heldout_gpt54 | narrative | 36 | 0.121 | [0.097, 0.145] | -1.125 |
| heldout_gpt54 | instructed | 36 | 0.046 | [0.019, 0.070] | -0.736 |
| heldout_gpt54 | true_named | 60 | 0.111 | [0.092, 0.130] | -1.025 |
| heldout_gpt54 | none | 60 | 0.123 | [0.103, 0.144] | -1.042 |
| heldout_gpt54 | true_blinded | 60 | 0.095 | [0.075, 0.115] | -1.133 |
| heldout_grok420 | sham | 180 | 0.072 | [0.061, 0.083] | -0.097 |
| heldout_grok420 | inverted | 36 | 0.081 | [0.053, 0.107] | -0.181 |
| heldout_grok420 | narrative | 36 | 0.083 | [0.055, 0.111] | -0.139 |
| heldout_grok420 | instructed | 36 | 0.030 | [0.004, 0.055] | -0.097 |
| heldout_grok420 | true_named | 60 | 0.078 | [0.060, 0.096] | -0.192 |
| heldout_grok420 | none | 60 | 0.087 | [0.066, 0.107] | -0.133 |
| heldout_grok420 | true_blinded | 60 | 0.056 | [0.038, 0.075] | -0.142 |
| heldout_sonnet46 | sham | 180 | 0.086 | [0.076, 0.095] | -0.033 |
| heldout_sonnet46 | inverted | 36 | 0.092 | [0.072, 0.113] | -0.028 |
| heldout_sonnet46 | narrative | 36 | 0.101 | [0.079, 0.123] | -0.083 |
| heldout_sonnet46 | instructed | 36 | 0.055 | [0.033, 0.078] | -0.083 |
| heldout_sonnet46 | true_named | 60 | 0.081 | [0.066, 0.098] | -0.050 |
| heldout_sonnet46 | none | 60 | 0.104 | [0.087, 0.123] | -0.033 |
| heldout_sonnet46 | true_blinded | 60 | 0.066 | [0.050, 0.081] | -0.050 |

### Exploratory: tau to reference and RBO(0.8) to displayed, by arm
| arm | n | Fisher-mean tau to reference | SD tau | RBO to displayed |
|---|---|---|---|---|
| sham | 180 | 0.842 | 0.079 | 0.494 |
| inverted | 36 | 0.826 | 0.080 | 0.167 |
| narrative | 36 | 0.814 | 0.075 | NA |
| instructed | 36 | 0.812 | 0.099 | 0.761 |
| true_named | 60 | 0.815 | 0.077 | 0.775 |
| none | 60 | 0.834 | 0.072 | NA |
| true_blinded | 60 | 0.840 | 0.065 | 0.802 |

### Rank flips vs reference by arm
| arm | n | mean flips | sd |
|---|---|---|---|
| sham | 180 | 6.089 | 2.823 |
| inverted | 36 | 7.306 | 3.106 |
| narrative | 36 | 6.444 | 2.455 |
| instructed | 36 | 7.972 | 3.858 |
| true_named | 60 | 6.483 | 2.528 |
| none | 60 | 5.900 | 2.384 |
| true_blinded | 60 | 6.617 | 2.591 |

## Measurement model: pooled home-advantage DIF
two-stage anchor-conditioned binomial GLM, session-clustered robust SEs; baseline arm for gamma = sham; rows = 796484, sessions = 469
| effect | log-odds | CI95 | OR | ETS delta | ETS cat | p |
|---|---|---|---|---|---|---|
| gamma_Target | -0.005 | [-0.044, 0.033] | 0.995 | -0.012 | A | 0.792 |
| delta_Target_x_true_named | -0.150 | [-0.236, -0.064] | 0.860 | -0.353 | A | 0.001 |
| total_home_advantage[true_named] | -0.156 | [-0.233, -0.079] | NA | -0.366 | A | NA |
| delta_Target_x_true_blinded | -0.103 | [-0.194, -0.011] | 0.902 | -0.242 | A | 0.028 |
| total_home_advantage[true_blinded] | -0.108 | [-0.191, -0.025] | NA | -0.254 | A | NA |
| delta_Target_x_inverted | 0.013 | [-0.067, 0.093] | 1.013 | 0.031 | A | 0.744 |
| total_home_advantage[inverted] | 0.008 | [-0.062, 0.078] | NA | 0.019 | A | NA |
| delta_Target_x_narrative | 0.007 | [-0.071, 0.085] | 1.007 | 0.016 | A | 0.866 |
| total_home_advantage[narrative] | 0.002 | [-0.066, 0.069] | NA | 0.004 | A | NA |
| delta_Target_x_instructed | 0.059 | [-0.063, 0.181] | 1.061 | 0.139 | A | 0.341 |
| total_home_advantage[instructed] | 0.054 | [-0.062, 0.170] | NA | 0.127 | A | NA |

Mixed (random-slopes) model: status = skipped; gamma = NA (sd NA); 3920500 Bernoulli rows exceed max_mixed_rows=400000
