#!/bin/bash
# The operator's own-hand run of the planning comparison: ONE live run of planning_compare.py with a throwaway OpenAI key.
# The key is typed hidden, held only in this process, and never written to a file. Spending stops at the budget (default 3.00 dollars).
#   bash run_compare.sh --check    reads only: finds Python, runs the offline tests, asks for nothing
#   bash run_compare.sh            the live run (about 10 minutes)
# Afterwards delete the throwaway key in the OpenAI dashboard. The results are in compare_run/planning_compare_result.json.
set -u
cd "$(dirname "$0")" || exit 1
MODE=${1:-run}
case "$MODE" in run|--check) ;; *) echo "REFUSED: unknown argument"; exit 1;; esac
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "REFUSED: Python 3.9 or newer needed"; exit 1; }
python3 -m unittest test_planning_compare 2>&1 | tail -3
[ "$MODE" = "--check" ] && { echo "Check done. Nothing was asked for and nothing was sent anywhere."; exit 0; }
[ -e compare_run ] && { echo "REFUSED: compare_run exists; rename it to run again."; exit 1; }
read -r -s -p "OpenAI key (hidden), then Enter: " OPENAI_API_KEY; echo
case "$OPENAI_API_KEY" in sk-*) ;; *) echo "REFUSED: that does not look like an OpenAI key."; exit 1;; esac
export OPENAI_API_KEY
mkdir compare_run
python3 planning_compare.py --live --budget "${COMPARE_BUDGET:-3.00}" --out compare_run/planning_compare_result.json 2>&1 | tee compare_run/run.log
unset OPENAI_API_KEY
if grep -R -q -F "sk-" compare_run 2>/dev/null; then echo "WARNING: secret-shaped text found in compare_run; do not share it."; else echo "No secret-shaped text in compare_run."; fi
