"""CLI: python -m ltm_extract --docs DIR --supplement FILE [--out SPEC.json]

Run from extractor/ with the reader on the path:
    PYTHONPATH=../reader python -m ltm_extract --docs ../.. \\
        --supplement supplements/allocations.json --out ../generator/specs/allocations.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import DocSet, ExtractionError, build_spec, load_supplement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ltm_extract", description=__doc__.splitlines()[0])
    parser.add_argument("--docs", required=True, help="folder holding the NN_*.docx originals")
    parser.add_argument("--supplement", required=True, help="analyst supplement JSON")
    parser.add_argument("--out", help="write the spec here instead of stdout")
    args = parser.parse_args(argv)

    try:
        result = build_spec(DocSet.load(args.docs), load_supplement(args.supplement))
    except ExtractionError as e:
        print("No spec written:", file=sys.stderr)
        for problem in e.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    for d in result.diagnostics:
        print(f"[{d.code}] {d.message}", file=sys.stderr)
    text = json.dumps(result.spec, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
