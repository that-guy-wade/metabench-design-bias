#!/usr/bin/env bash
# Confirmatory run driver: docs/BUILD_REPORT.md section 2 for the three main pools in sequence (factual, math, code:
# shortest first, so a complete pool exists soonest; decision 2026-10-25 10:58 UTC), frozen sizes (runner defaults).
# Per pool: verify -> precompute -> register -> run -> health.  A failing phase stops the script.
# Progress goes to docs/RUN_PROGRESS.md as plaintext rows (ids, counts, timings, exit codes only; never scores).
# Usage: scripts_run_confirmatory.sh [--dry-run]     env: MB_RUN_ROOT MB_RUN_PROGRESS MB_POOLS MB_CONCURRENCY MB_PANEL_CONCURRENCY
#        MB_LIVE_RESCORE_WAIT_S (when set and non-empty: passed as --live-rescore-wait-s to register and run; the runner
#        records it in the registration and refuses `run` if it differs; unset = blocking live re-score)
set -euo pipefail

ROOT="${MB_RUN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
PROGRESS="${MB_RUN_PROGRESS:-$ROOT/docs/RUN_PROGRESS.md}"
POOLS="${MB_POOLS:-factual math code}"
DRY=0
LIVE=()
if [ -n "${MB_LIVE_RESCORE_WAIT_S:-}" ]; then LIVE=(--live-rescore-wait-s "$MB_LIVE_RESCORE_WAIT_S"); fi
if [ "${1:-}" = "--dry-run" ]; then DRY=1; fi
cd "$ROOT"

pool_path() {
  case "$1" in
    math) echo pools/math/pool.jsonl ;;
    code) echo pools/code/pool.jsonl ;;
    factual) echo pools/factual_qa/pool.jsonl ;;
    *) echo "unknown pool name: $1" >&2; return 1 ;;
  esac
}

progress() {  # pool phase exit elapsed counts
  if [ ! -f "$PROGRESS" ]; then
    mkdir -p "$(dirname "$PROGRESS")"
    printf '# Confirmatory run progress (plaintext: ids, counts, timings, exit codes only)\n\n' >"$PROGRESS"
    printf '| time (UTC) | pool | phase | exit | elapsed | counts |\n|---|---|---|---|---|---|\n' >>"$PROGRESS"
  fi
  printf '| %s | %s | %s | exit=%s | %ss | %s |\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" "$5" >>"$PROGRESS"
}

refuse() {  # reason
  progress - phase0 3 0 "REFUSED: $1"
  echo "REFUSED: $1"
  exit 3
}

# ---- phase 0: frozen code, sealing material, pool files, Google credential ---------------------------------------
[ -f prereg/frozen_code.json ] || refuse "prereg/frozen_code.json missing"
[ -d sealing/gnupg ] || refuse "sealing keyring sealing/gnupg missing"
[ -f prereg/sealing_key.json ] || refuse "prereg/sealing_key.json missing"
for NAME in $POOLS; do
  P="$(pool_path "$NAME")" || refuse "unknown pool name $NAME"
  [ -f "$P" ] || refuse "pool file $P missing"
done
# Google runs through Vertex AI on the box's gcloud credential (metabench/llm.py); without a token the precompute
# would fail on its first Google call.  The token is checked for presence only and never written anywhere.
GTOK="$(timeout 60 gcloud auth print-access-token 2>/dev/null || true)"
[ -n "$GTOK" ] || refuse "gcloud auth print-access-token returned no token (Vertex AI credential missing)"
unset GTOK
mkdir -p logs
T0=$(date +%s)
if "$PY" scripts_freeze.py verify >logs/run_confirmatory_phase0_verify.log 2>&1; then
  progress - phase0 0 $(( $(date +%s) - T0 )) "frozen code verified"
else
  DETAIL=$("$PY" -c 'import json,sys; t=open(sys.argv[1]).read(); r=json.loads(t[:t.rfind("}")+1]); print("mismatched=%s missing=%s unfrozen=%s" % (r.get("mismatched"), r.get("missing"), r.get("unfrozen")))' logs/run_confirmatory_phase0_verify.log 2>/dev/null || echo "see logs/run_confirmatory_phase0_verify.log")
  refuse "frozen code mismatch: $DETAIL"
fi

# ---- per pool phases -------------------------------------------------------------------------------------------
phase() {  # name phase cmd... : runs cmd, logs it, writes the progress row, stops the script on failure
  local NAME="$1" PHASE="$2"; shift 2
  local LOG="logs/run_confirmatory_${NAME}_${PHASE}.log" T0 RC=0 COUNTS=""
  if [ "$DRY" = 1 ]; then
    echo "DRY $*"
    progress "$NAME" "$PHASE" dry 0 "-"
    return 0
  fi
  T0=$(date +%s)
  "$@" >>"$LOG" 2>&1 || RC=$?
  case "$PHASE" in
    register) COUNTS="sessions=$("$PY" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["sessions"]))' "prereg/confirmatory_hashes_${NAME}.json" 2>/dev/null || echo "?")" ;;
    run) COUNTS="done=$(grep -c '] done  ' "$LOG" || true) valid_true=$(grep '] done  ' "$LOG" | grep -c 'valid=True' || true) valid_false=$(grep '] done  ' "$LOG" | grep -c 'valid=False' || true)" ;;
    health) if [ "$RC" -eq 0 ]; then COUNTS="PASSED"; else COUNTS="FAILED"; fi ;;
    *) COUNTS="-" ;;
  esac
  progress "$NAME" "$PHASE" "$RC" $(( $(date +%s) - T0 )) "$COUNTS"
  [ "$RC" -eq 0 ] || { echo "STOPPED at ${NAME}/${PHASE} exit=${RC}"; exit 4; }
}

for NAME in $POOLS; do
  P="$(pool_path "$NAME")"
  phase "$NAME" verify "$PY" scripts_freeze.py verify
  phase "$NAME" precompute "$PY" scripts_runner.py precompute --pool "$P" --pool-name "$NAME" --samples 5 --panel-concurrency "${MB_PANEL_CONCURRENCY:-96}"
  phase "$NAME" register "$PY" scripts_runner.py register --pool "$P" --pool-name "$NAME" --samples 5 ${LIVE[@]+"${LIVE[@]}"}
  phase "$NAME" run "$PY" scripts_runner.py run --pool "$P" --pool-name "$NAME" --samples 5 --concurrency "${MB_CONCURRENCY:-16}" ${LIVE[@]+"${LIVE[@]}"}
  HEALTH=("$PY" scripts_health_check.py --view "health/health_view_${NAME}.jsonl" --registered "prereg/confirmatory_hashes_${NAME}.json")
  if [ -f "prereg/confirmatory_replacements_${NAME}.json" ]; then HEALTH+=(--replacements "prereg/confirmatory_replacements_${NAME}.json"); fi
  phase "$NAME" health "${HEALTH[@]}"
done
echo "ALL POOLS DONE"
