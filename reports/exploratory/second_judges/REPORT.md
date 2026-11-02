# Second judges for the instructed-arm labels (EXPLORATORY, 2026-11-04)

**What.** The 102 main-experiment instructed sessions were re-labelled by two more judges from other developers,
gemini-4-argon and grok-4.7. They used the released `judge_c1.py` rubric and exactly the inputs GPT-5.5 judged
(`data/exploratory/controls/judge.tar.gz`). Labels are COMPLIED / PARTIAL_AMBIGUOUS / REFUSED.

## Result

**Pairwise agreement:**

| judges | sessions agreeing |
|---|---|
| GPT-5.5 ~ Gemini 4 Argon | 98/102 |
| GPT-5.5 ~ Grok 4.7 | 100/102 |
| Gemini 4 Argon ~ Grok 4.7 | 98/102 |

All three agree on **97/102**.

The majority label differs from the GPT-5.5 label in one session: a gemini31pro PARTIAL_AMBIGUOUS becomes COMPLIED.
Per-model counts are in `data/exploratory/second_judges/second_judges.json`. Raw judge text is not shipped, because it
can quote licence-restricted maths items.

## Run it

`code/exploratory/second_judges/second_judges.py JUDGE_DIR OUT_DIR`, where JUDGE_DIR is the extracted `judge.tar.gz`.
The script needs `readers.py`, a small multi-provider client, next to it.
