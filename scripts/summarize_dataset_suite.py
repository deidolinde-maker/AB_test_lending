from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DatasetResult:
    dataset: str
    status: str
    name: str
    message: str
    mtime: float


@dataclass
class BugReportRow:
    case_name: str
    steps: str
    expected: str
    actual: str
    description: str


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
        details = payload.get("statusDetails") or {}
        rows.append(
            DatasetResult(
                dataset=dataset,
                status=str(payload.get("status") or "unknown"),
                name=str(payload.get("name") or payload.get("fullName") or result_file.stem),
                message=str(details.get("message") or "").strip(),
                mtime=result_file.stat().st_mtime,
            )
        )
    return rows


def _latest(rows: list[DatasetResult]) -> list[DatasetResult]:
    by_key: dict[tuple[str, str], DatasetResult] = {}
    for row in rows:
        key = (row.dataset, row.name)
        prev = by_key.get(key)
        if prev is None or row.mtime > prev.mtime:
            by_key[key] = row
    return list(by_key.values())


def _short_line(message: str) -> str:
    return (message.splitlines()[0] if message else "").strip()


def _normalize_message(message: str) -> str:
    return " ".join(line.strip() for line in message.splitlines() if line.strip())


def _extract_case_name(test_name: str) -> str:
    # Example:
    # test_search_variant_b[mts_internet_online__domain_without_region__profit__B__B_moscow_lipovy_park-chromium]
    if "[" not in test_name or "]" not in test_name:
        return test_name
    bracket = test_name[test_name.find("[") + 1 : test_name.rfind("]")]
    if "__" not in bracket:
        return bracket
    parts = bracket.split("__")
    if len(parts) >= 5:
        return parts[4].split("-")[0]
    return bracket


def _build_bug_report_row(row: DatasetResult) -> BugReportRow:
    message = row.message or ""
    case_name = _extract_case_name(row.name)

    if "Expected streets request to hit v2 endpoint" in message:
        observed = ""
        m = re.search(r"Observed search-like URLs:\s*(.+)$", message, flags=re.S)
        if m:
            observed = m.group(1).strip()
        return BugReportRow(
            case_name=case_name,
            steps="Открыть форму, ввести улицу и дом, проверить сетевые запросы поиска адреса.",
            expected=(
                "Для варианта B запросы улиц/домов должны идти через v2 "
                "(`/api_protected/v2/search/*` или `/wp-json/cf7proxy/v2/*`)."
            ),
            actual=observed or _short_line(message),
            description="Для варианта B фактически используется v1 endpoint вместо v2.",
        )

    if "Expected houses request to hit v2 endpoint" in message:
        observed = ""
        m = re.search(r"Observed search-like URLs:\s*(.+)$", message, flags=re.S)
        if m:
            observed = m.group(1).strip()
        return BugReportRow(
            case_name=case_name,
            steps="После выбора улицы запросить дома и проверить сетевые запросы backend.",
            expected=(
                "Запрос домов для варианта B должен идти через v2 "
                "(`/api_protected/v2/search/houses` или `/wp-json/cf7proxy/v2/houses`)."
            ),
            actual=observed or _short_line(message),
            description="Backend маршрутизация домов для B-ветки не соответствует ожидаемой v2 схеме.",
        )

    if "Step: Validate selected address ID" in message:
        exp = ""
        act = ""
        m = re.search(r"Expected:\s*(.+)\s+Actual:\s*(.+)", _normalize_message(message))
        if m:
            exp, act = m.group(1).strip(), m.group(2).strip()
        return BugReportRow(
            case_name=case_name,
            steps="Выбрать улицу и дом из саджеста, затем сверить выбранный ID адреса.",
            expected=f"ID адреса должен совпасть с эталоном ({exp})" if exp else "ID адреса должен совпасть с эталоном.",
            actual=f"Получен другой ID: {act}" if act else _short_line(message),
            description="Система выбрала адрес, но его ID не совпал с ожидаемым.",
        )

    if "Expected house in suggest" in message:
        expected_house = ""
        near = ""
        m = re.search(r"Expected house in suggest:\s*([^\.]+)\.?\s*(.*)$", message, flags=re.S)
        if m:
            expected_house, near = m.group(1).strip(), m.group(2).strip()
        return BugReportRow(
            case_name=case_name,
            steps="После ввода дома дождаться саджеста и проверить, что целевой дом есть в списке.",
            expected=(
                f"В саджесте должен присутствовать дом `{expected_house}`."
                if expected_house
                else "В саджесте должен присутствовать ожидаемый дом."
            ),
            actual=near or _short_line(message),
            description="Саджест домов не содержит точное совпадение ожидаемого значения.",
        )

    if "House input did not become editable" in message:
        return BugReportRow(
            case_name=case_name,
            steps="После выбора улицы перейти к вводу дома.",
            expected="Поле дома должно стать доступным для ввода.",
            actual=_short_line(message),
            description="Поле дома осталось заблокированным, продолжение сценария невозможно.",
        )

    return BugReportRow(
        case_name=case_name,
        steps="См. пошаговый сценарий в тест-кейсе и вложениях Allure.",
        expected="Сценарий должен завершиться без ошибок и с валидными проверками.",
        actual=_short_line(message) or "Ошибка без детализированного текста.",
        description="Обнаружено отклонение от ожидаемого поведения, требуется анализ вложений.",
    )


def _md(value: str) -> str:
    return value.replace("\n", "<br>").replace("|", "\\|")


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

        lines.append("")
        lines.append("## Баг-репорт (RU)")
        lines.append("")
        lines.append("| Кейс | Шаги | Ожидаемый результат | Фактический результат | Описание бага |")
        lines.append("|---|---|---|---|---|")
        for row in sorted(failed_like, key=lambda x: (x.dataset, x.name)):
            bug = _build_bug_report_row(row)
            lines.append(
                f"| {_md(f'[{row.dataset}] {bug.case_name}')} | {_md(bug.steps)} | "
                f"{_md(bug.expected)} | {_md(bug.actual)} | {_md(bug.description)} |"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize dataset-suite Allure results")
    parser.add_argument("--site", required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--allure-root", default="artifacts/allure-results")
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.allure_root) / args.site / "datasets" / args.run_tag
    rows = _latest(_load_results(root))
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
