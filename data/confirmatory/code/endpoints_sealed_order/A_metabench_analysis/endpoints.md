# MetaBench endpoints

## Primary: Psi (sham arm, identity = blinded)
| quantity | value |
|---|---|
| n | 60 |
| n_designers | 12 |
| psi | -0.000 |
| z | -0.000 |
| p_one_sided | 0.512 |
| p_two_sided | 0.992 |
| ci95_cluster_tau | [-0.063, 0.065] |
| ci95_bench_tau | [-0.049, 0.053] |
| null_mean_z | 0.001 |
| null_sd_z | 0.029 |
| cluster_bootstrap_degenerate | False |

| designer | n | mean tau |
|---|---|---|
| sonnet55 | 5 | -0.062 |
| grok43 | 5 | -0.042 |
| grok47 | 5 | 0.022 |
| gpt6luna | 5 | 0.031 |
| gpt55 | 5 | -0.005 |
| gemini31pro | 5 | -0.042 |
| grok45 | 5 | 0.000 |
| gemini38flash | 5 | -0.036 |
| gpt61sol | 5 | -0.143 |
| gemini4argon | 5 | -0.013 |
| fable51 | 5 | 0.107 |
| opus5 | 5 | 0.178 |

### Psi by identity arm (descriptive companions; the primary is the pseudonymous estimate)
| identity arm | n | n designers | psi | p one-sided | CI95 cluster tau |
|---|---|---|---|---|---|
| blinded | 60 | 12 | -0.000 | 0.512 | [-0.063, 0.065] |
| true | 60 | 12 | 0.487 | 0.000 | [0.457, 0.518] |
| false | 60 | 12 | 0.486 | 0.000 | [0.452, 0.518] |
| pooled | 180 | 12 | 0.340 | 0.000 | [0.295, 0.382] |

## Secondary (Holm-corrected)
| endpoint | estimate | CI95 (cluster) | CI95 (bench) | p | Holm p |
|---|---|---|---|---|---|
| displayed-leader rank gain (sham), positions | -0.227 | [-0.493, 0.043] | [-0.436, -0.027] | 0.966 | 1.000 |
| self-rank gain true vs blinded, positions | 0.054 | [-0.293, 0.342] | [0.036, 0.066] | 0.337 | 1.000 |
| inverted-arm tau minus none-arm tau (Fisher z) | -0.021 | [-0.159, 0.093] | [-0.039, -0.024] | 0.649 | 1.000 |
| true-minus-none tau to reference (Fisher z) | 0.053 | [-0.055, 0.172] | [0.049, 0.058] | 0.129 | 0.515 |

### Leader rank gain by arm
| arm | n | gain | CI95 cluster | p |
|---|---|---|---|---|
| sham | 178 | -0.227 | [-0.493, 0.043] | 0.966 |
| narrative | 34 | 0.010 | [-0.263, 0.278] | 0.470 |
| true_named | 60 | 0.075 | [-0.250, 0.508] | 0.460 |
| instructed | 31 | 0.169 | [-0.600, 1.006] | 0.020 |

### Self-rank by identity arm (mean produced rank of the designer's own model)
- blinded: 6.325
- false: 6.025
- true: 6.271

### Placebo separation |sonnet55 - placebo| by arm
| arm | n | mean abs sep | CI95 | excess over none | p vs none | signed sep (displayed hi - lo) | CI95 |
|---|---|---|---|---|---|---|---|
| narrative | 36 | 0.007 | [0.006, 0.009] | -0.001 | 0.499 | NA | NA |
| sham | 180 | 0.009 | [0.008, 0.010] | 0.001 | 0.145 | 0.000 | [-0.002, 0.003] |
| inverted | 35 | 0.010 | [0.008, 0.011] | 0.002 | 0.131 | 0.007 | [0.004, 0.010] |
| true_named | 60 | 0.011 | [0.009, 0.014] | 0.004 | 0.009 | NA | NA |
| instructed | 36 | 0.010 | [0.008, 0.012] | 0.002 | 0.094 | 0.003 | [-0.001, 0.006] |
| true_blinded | 60 | 0.008 | [0.007, 0.010] | 0.000 | 0.640 | 0.004 | [0.001, 0.006] |
| none | 60 | 0.008 | [0.007, 0.009] | NA | NA | NA | NA |

### Held-out model shift (produced - reference score; rank shift)
| model | arm | n | score shift | CI95 | rank shift |
|---|---|---|---|---|---|
| heldout_gemini35flash | narrative | 36 | -0.008 | [-0.020, 0.005] | -1.625 |
| heldout_gemini35flash | sham | 180 | -0.055 | [-0.064, -0.046] | -1.053 |
| heldout_gemini35flash | inverted | 35 | -0.046 | [-0.060, -0.032] | -0.786 |
| heldout_gemini35flash | true_named | 60 | -0.052 | [-0.067, -0.038] | -1.083 |
| heldout_gemini35flash | instructed | 36 | -0.027 | [-0.041, -0.015] | -0.583 |
| heldout_gemini35flash | true_blinded | 60 | -0.051 | [-0.067, -0.036] | -1.225 |
| heldout_gemini35flash | none | 60 | -0.015 | [-0.024, -0.005] | -1.642 |
| heldout_gpt54 | narrative | 36 | -0.002 | [-0.013, 0.010] | -2.208 |
| heldout_gpt54 | sham | 180 | -0.043 | [-0.051, -0.036] | -2.233 |
| heldout_gpt54 | inverted | 35 | -0.035 | [-0.046, -0.024] | -2.286 |
| heldout_gpt54 | true_named | 60 | -0.041 | [-0.053, -0.029] | -2.350 |
| heldout_gpt54 | instructed | 36 | -0.019 | [-0.032, -0.008] | -1.833 |
| heldout_gpt54 | true_blinded | 60 | -0.036 | [-0.050, -0.024] | -2.208 |
| heldout_gpt54 | none | 60 | -0.010 | [-0.018, -0.001] | -2.250 |
| heldout_grok420 | narrative | 36 | -0.019 | [-0.029, -0.010] | -0.028 |
| heldout_grok420 | sham | 180 | -0.041 | [-0.046, -0.036] | -0.983 |
| heldout_grok420 | inverted | 35 | -0.031 | [-0.039, -0.022] | -1.214 |
| heldout_grok420 | true_named | 60 | -0.041 | [-0.048, -0.034] | -0.967 |
| heldout_grok420 | instructed | 36 | -0.022 | [-0.034, -0.011] | -0.653 |
| heldout_grok420 | true_blinded | 60 | -0.035 | [-0.044, -0.026] | -1.025 |
| heldout_grok420 | none | 60 | -0.026 | [-0.034, -0.018] | -0.133 |
| heldout_sonnet46 | narrative | 36 | -0.034 | [-0.055, -0.012] | -0.278 |
| heldout_sonnet46 | sham | 180 | -0.106 | [-0.120, -0.093] | -0.164 |
| heldout_sonnet46 | inverted | 35 | -0.091 | [-0.112, -0.071] | -0.143 |
| heldout_sonnet46 | true_named | 60 | -0.099 | [-0.121, -0.078] | -0.233 |
| heldout_sonnet46 | instructed | 36 | -0.056 | [-0.081, -0.032] | -0.236 |
| heldout_sonnet46 | true_blinded | 60 | -0.097 | [-0.123, -0.074] | -0.175 |
| heldout_sonnet46 | none | 60 | -0.043 | [-0.061, -0.025] | -0.175 |

### Exploratory: tau to reference and RBO(0.8) to displayed, by arm
| arm | n | Fisher-mean tau to reference | SD tau | RBO to displayed |
|---|---|---|---|---|
| narrative | 36 | 0.829 | 0.107 | NA |
| sham | 180 | 0.858 | 0.061 | 0.532 |
| inverted | 35 | 0.839 | 0.076 | 0.170 |
| true_named | 60 | 0.863 | 0.055 | 0.832 |
| instructed | 36 | 0.810 | 0.065 | 0.820 |
| true_blinded | 60 | 0.830 | 0.058 | 0.851 |
| none | 60 | 0.832 | 0.096 | NA |

### Rank flips vs reference by arm
| arm | n | mean flips | sd |
|---|---|---|---|
| narrative | 36 | 6.056 | 3.464 |
| sham | 180 | 5.428 | 2.222 |
| inverted | 35 | 6.971 | 2.945 |
| true_named | 60 | 4.733 | 1.774 |
| instructed | 36 | 7.639 | 2.554 |
| true_blinded | 60 | 6.800 | 2.268 |
| none | 60 | 6.050 | 3.121 |

## Measurement model: pooled home-advantage DIF
two-stage anchor-conditioned binomial GLM, session-clustered robust SEs; baseline arm for gamma = sham; rows = 816702, sessions = 481
| effect | log-odds | CI95 | OR | ETS delta | ETS cat | p |
|---|---|---|---|---|---|---|
| gamma_Target | -0.085 | [-0.144, -0.025] | 0.919 | -0.199 | A | 0.006 |
| delta_Target_x_true_named | 0.399 | [0.280, 0.519] | 1.491 | 0.939 | A | 0.000 |
| total_home_advantage[true_named] | 0.315 | [0.211, 0.418] | NA | 0.740 | A | NA |
| delta_Target_x_true_blinded | 0.483 | [0.334, 0.632] | 1.621 | 1.135 | B | 0.000 |
| total_home_advantage[true_blinded] | 0.398 | [0.261, 0.535] | NA | 0.936 | A | NA |
| delta_Target_x_inverted | 0.062 | [-0.029, 0.152] | 1.064 | 0.145 | A | 0.181 |
| total_home_advantage[inverted] | -0.023 | [-0.091, 0.045] | NA | -0.054 | A | NA |
| delta_Target_x_narrative | 0.005 | [-0.103, 0.113] | 1.005 | 0.011 | A | 0.930 |
| total_home_advantage[narrative] | -0.080 | [-0.170, 0.010] | NA | -0.188 | A | NA |
| delta_Target_x_instructed | 0.081 | [-0.033, 0.196] | 1.085 | 0.191 | A | 0.164 |
| total_home_advantage[instructed] | -0.003 | [-0.101, 0.095] | NA | -0.008 | A | NA |

Mixed (random-slopes) model: status = skipped; gamma = NA (sd NA); 4062631 Bernoulli rows exceed max_mixed_rows=400000
