from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DatasetResult:
    dataset: str
    status: str
    name: str


def _load_results(root: Path) -> list[DatasetResult]:
    rows: list[DatasetResult] = []
    if not root.exists():
        return rows
    for result_file in root.rglob("*-result.json"):
        rel = result_file.relative_to(root).parts
        if len(rel) < 2:
            continue
        dataset = rel[0]
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            DatasetResult(
                dataset=dataset,
                status=str(payload.get("status") or "unknown"),
                name=str(payload.get("name") or payload.get("fullName") or result_file.stem),
            )
        )
    return rows


def _render(rows: list[DatasetResult], run_tag: str) -> str:
    lines: list[str] = []
    lines.append("# Dataset Suite Summary")
    lines.append("")
    lines.append(f"Run tag: `{run_tag}`")
    lines.append("")

    if not rows:
        lines.append("No result files found.")
        return "\n".join(lines)

    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[row.dataset][row.status] += 1

    lines.append("| dataset | passed | failed | skipped | broken | other |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for dataset in sorted(grouped.keys()):
        c = grouped[dataset]
        other = sum(v for k, v in c.items() if k not in {"passed", "failed", "skipped", "broken"})
        lines.append(
            f"| {dataset} | {c.get('passed', 0)} | {c.get('failed', 0)} | "
            f"{c.get('skipped', 0)} | {c.get('broken', 0)} | {other} |"
        )

    failed_like = [r for r in rows if r.status in {"failed", "broken"}]
    if failed_like:
        lines.append("")
        lines.append("## Failed Cases")
        for row in sorted(failed_like, key=lambda x: (x.dataset, x.name)):
            lines.append(f"- [{row.dataset}] {row.name} ({row.status})")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize dataset-suite Allure results")
    parser.add_argument("--site", required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--allure-root", default="artifacts/allure-results")
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.allure_root) / args.site / "datasets" / args.run_tag
    rows = _load_results(root)
    report = _render(rows, args.run_tag)
    print(report)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"\nSaved summary: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
