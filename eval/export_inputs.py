"""Export public scenarios using an explicit whitelist; labels never enter the system."""
from __future__ import annotations

import argparse
from pathlib import Path

from eval.common import ROOT, read_jsonl, system_input, write_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("visible", "development", "kt1"), default="visible")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    name = {"visible": "visible.jsonl", "development": "development.jsonl", "kt1": "kt1_examples.jsonl"}[args.source]
    source = ROOT / "eval" / name
    destination = args.output.resolve()
    if destination.is_relative_to(ROOT) and not destination.is_relative_to(ROOT / "eval/runs"):
        parser.error("Inside this repository, output is allowed only under ignored eval/runs")
    write_jsonl(args.output, [system_input(c) for c in read_jsonl(source)])
    print("Exported system inputs without labels. No system was run.")


if __name__ == "__main__":
    main()
