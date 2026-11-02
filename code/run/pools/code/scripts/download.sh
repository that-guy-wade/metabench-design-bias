#!/bin/bash
# Download the code_contests parquet shards we use (test, valid, train 0..N-1) into pools/_work/code/parquet.
# Usage: download.sh [N_TRAIN_SHARDS]   (default 10). Re-runnable; curl -C - resumes/skips complete files.
# Shard names come from the HF API listing of deepmind/code_contests (revision main, listed 2026-10-25).
set -euo pipefail
N=${1:-10}
DEST=/path/to/metabench/run/pools/_work/code/parquet
mkdir -p "$DEST"
BASE=https://huggingface.co/datasets/deepmind/code_contests/resolve/main/data
FILES="test-00000-of-00001-9c49eeff30aacaa8.parquet valid-00000-of-00001-5e672c5751f060d3.parquet"
TRAIN="train-00000-of-00039-e991a271dbfa9925.parquet train-00001-of-00039-e092fe56fda18715.parquet train-00002-of-00039-9cea23812e920e41.parquet train-00003-of-00039-e3822fccad6e083a.parquet train-00004-of-00039-cefe355b4667b27e.parquet train-00005-of-00039-b7580d2d846c2136.parquet train-00006-of-00039-65184bb9f7d61fde.parquet train-00007-of-00039-05785de21e8b8429.parquet train-00008-of-00039-7246e6b7423b404f.parquet train-00009-of-00039-b8c920f6629b57b2.parquet train-00010-of-00039-6de28ba20654f69b.parquet train-00011-of-00039-5de236be5188959d.parquet train-00012-of-00039-da9476a39a1bdbb7.parquet train-00013-of-00039-30b8c3829ee3b962.parquet train-00014-of-00039-dc3ebb07a3cba8e4.parquet train-00015-of-00039-19ccd7331d695677.parquet train-00016-of-00039-bf38b0908b322307.parquet train-00017-of-00039-ae5533a2f822e6ef.parquet train-00018-of-00039-8c793837880f5507.parquet train-00019-of-00039-d688fad5ee604390.parquet train-00020-of-00039-5d59387098675b73.parquet train-00021-of-00039-b257bf03d6876780.parquet train-00022-of-00039-1cfd39fa43c1917c.parquet train-00023-of-00039-d078bcb55e45cbf0.parquet train-00024-of-00039-f4e3da0e5661e6d1.parquet train-00025-of-00039-3f6ebfbaba5f4c70.parquet train-00026-of-00039-7d4898300894cbbe.parquet train-00027-of-00039-f8196766547533a2.parquet train-00028-of-00039-79a302af3c924863.parquet train-00029-of-00039-2b6615897d038115.parquet train-00030-of-00039-4135cc54050afc22.parquet train-00031-of-00039-40309dd907c042b7.parquet train-00032-of-00039-7b7d2068a3d9c359.parquet train-00033-of-00039-53b0f749aacff9c1.parquet train-00034-of-00039-a36ff0bff7d2a76f.parquet train-00035-of-00039-d28f9be60314601f.parquet train-00036-of-00039-146e1a11c054aeab.parquet train-00037-of-00039-995207c374a4e6f2.parquet train-00038-of-00039-96a59dd6a98cd075.parquet"
i=0
for f in $TRAIN; do
  if [ "$i" -lt "$N" ]; then FILES="$FILES $f"; fi
  i=$((i+1))
done
for f in $FILES; do echo "$f"; done | xargs -P 3 -I{} sh -c 'curl -sSL --retry 3 -C - -o "'"$DEST"'/{}" "'"$BASE"'/{}" && echo done {}'
