#!/usr/bin/env bash
# Shows the pipeline refusing instead of guessing. Each case breaks one thing in a
# copy of the ACME Expenses supplements and runs the runner without Maven.
#   demo/refusal_demo.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
python3 "$ROOT/demo/acme-expenses/make_docs.py" "$WORK/docs" > /dev/null

case_run() {  # title, python edit applied to the copied supplements folder
  echo "=== $1"
  rm -rf "$WORK/sup" "$WORK/out" && cp -r "$ROOT/demo/acme-expenses/supplements" "$WORK/sup"
  python3 - "$WORK/sup" <<PY
import json, sys
from pathlib import Path
sup = Path(sys.argv[1])
def edit(name, fn):
    p = sup / name
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
$2
PY
  python3 "$ROOT/tools/run_ltm_demo.py" --docs "$WORK/docs" --supplements "$WORK/sup" \
      --out "$WORK/out" --skip-maven 2>&1 | grep -v '^\w* \[' | sed 's/^/    /'
  echo
}

case_run "1. A service task with no service binding (nobody said what 'Save Expense Claim' calls)" \
  'edit("submit_expense_claim.json", lambda d: d["design"]["nodes"]["saveExpenseClaim"].pop("service"))'

case_run "2. An application name the documents never state" \
  'edit("submit_expense_claim.json", lambda d: d["application"].update(name="ACME Travel"))'

case_run "3. A quote that is not in the cited paragraph" \
  'edit("review_expense_claim.json", lambda d: d["design"]["nodes"]["recordApproval"]["support"][0].update(quote="Approvals are emailed to finance"))'

case_run "4. A process name that is not a documented process model" \
  'edit("review_expense_claim.json", lambda d: d.update(process="ACME Review Expense"))'
