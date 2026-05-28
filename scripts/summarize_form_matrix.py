from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class ResultRow:
    url_type: str
    variant: str
    form: str
    status: str
    name: str
    message: str
    mtime: float


def _signature(message: str) -> str:
    if "Expected house in suggest" in message:
        return "HOUSE_FORMAT_MISMATCH"
    if "Validate selected address ID" in message:
        return "HOUSE_ID_MISMATCH"
    if "Expected streets request to hit v2 endpoint" in message:
        return "V2_STREETS_ENDPOINT_MISSING"
    if "Expected houses request to hit v2 endpoint" in message:
        return "V2_HOUSES_ENDPOINT_MISSING"
    if "Required form" in message and "is not present" in message:
        return "REQUIRED_FORM_MISSING"
    return "OTHER_FAILURE"


def _extract_case_name(test_name: str) -> str:
    if "[" not in test_name or "]" not in test_name:
        return test_name
    bracket = test_name[test_name.find("[") + 1 : test_name.rfind("]")]
    if "__" not in bracket:
        return bracket
    parts = bracket.split("__")
    if len(parts) >= 5:
        return parts[4].split("-")[0]
    return bracket


def _normalize_message(message: str) -> str:
    return " ".join(line.strip() for line in message.splitlines() if line.strip())


def _bug_details(message: str) -> tuple[str, str, str]:
    if "Expected streets request to hit v2 endpoint" in message:
        m = re.search(r"Observed search-like URLs:\s*(.+)$", message, flags=re.S)
        observed = m.group(1).strip() if m else message.splitlines()[0]
        return (
            "Для варианта B запросы поиска улиц/домов должны идти через v2 endpoint.",
            observed,
            "Для варианта B фактически используется v1 endpoint вместо v2.",
        )
    if "Step: Validate selected address ID" in message:
        m = re.search(r"Expected:\s*(.+)\s+Actual:\s*(.+)", _normalize_message(message))
        if m:
            return (
                f"ID адреса должен совпасть с эталоном ({m.group(1).strip()}).",
                f"Получен другой ID: {m.group(2).strip()}",
                "Выбранный ID адреса не совпал с ожидаемым.",
            )
    if "Expected house in suggest" in message:
        m = re.search(r"Expected house in suggest:\s*([^\.]+)\.?\s*(.*)$", message, flags=re.S)
        if m:
            return (
                f"В саджесте должен присутствовать дом `{m.group(1).strip()}`.",
                m.group(2).strip() or message.splitlines()[0],
                "Саджест домов не содержит ожидаемое значение.",
            )
    if "House input did not become editable" in message:
        return (
            "Поле дома должно стать доступным для ввода после выбора улицы.",
            message.splitlines()[0],
            "Поле дома осталось заблокированным.",
        )
    first = message.splitlines()[0] if message else "Ошибка без текста."
    return (
        "Сценарий должен завершиться без ошибок.",
        first,
        "Обнаружено отклонение поведения от ожидаемого.",
    )


def _md(value: str) -> str:
    return value.replace("\n", "<br>").replace("|", "\\|")


def _iter_result_files(site_root: Path, url_types: set[str] | None) -> Iterable[Path]:
    for result_file in site_root.rglob("*-result.json"):
        rel_parts = result_file.relative_to(site_root).parts
        if len(rel_parts) < 4:
            continue
        url_type = rel_parts[0]
        if url_types and url_type not in url_types:
            continue
        yield result_file


def _load_rows(site_root: Path, url_types: set[str] | None) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for path in _iter_result_files(site_root, url_types):
        rel_parts = path.relative_to(site_root).parts
        url_type, variant, form = rel_parts[0], rel_parts[1], rel_parts[2]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = str(payload.get("status") or "unknown")
        name = str(payload.get("name") or payload.get("fullName") or path.stem)
        details = payload.get("statusDetails") or {}
        message = str(details.get("message") or "")
        rows.append(
            ResultRow(
                url_type=url_type,
                variant=variant,
                form=form,
                status=status,
                name=name,
                message=message,
                mtime=path.stat().st_mtime,
            )
        )
    return rows


def _latest(rows: list[ResultRow]) -> list[ResultRow]:
    latest_by_key: dict[tuple[str, str, str, str], ResultRow] = {}
    for row in rows:
        key = (row.url_type, row.variant, row.form, row.name)
        prev = latest_by_key.get(key)
        if prev is None or row.mtime > prev.mtime:
            latest_by_key[key] = row
    return list(latest_by_key.values())


def _render_markdown(rows: list[ResultRow]) -> str:
    lines: list[str] = []
    if not rows:
        return "No Allure result files found for selected scope."

    by_group: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_group[(row.url_type, row.variant, row.form)][row.status] += 1

    lines.append("# Form Matrix Summary")
    lines.append("")
    lines.append("| url_type | variant | form | passed | failed | skipped | broken | other |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for (url_type, variant, form) in sorted(by_group.keys()):
        c = by_group[(url_type, variant, form)]
        other = sum(v for k, v in c.items() if k not in {"passed", "failed", "skipped", "broken"})
        lines.append(
            f"| {url_type} | {variant} | {form} | {c.get('passed', 0)} | {c.get('failed', 0)} | "
            f"{c.get('skipped', 0)} | {c.get('broken', 0)} | {other} |"
        )

    failed_like = [r for r in rows if r.status in {"failed", "broken"}]
    if failed_like:
        signature_counts = Counter(_signature(r.message) for r in failed_like)
        lines.append("")
        lines.append("## Failure Signatures")
        for signature, count in sorted(signature_counts.items()):
            lines.append(f"- {signature}: {count}")

        lines.append("")
        lines.append("## Failed Cases")
        for row in sorted(failed_like, key=lambda r: (r.url_type, r.variant, r.form, r.name)):
            first_line = row.message.splitlines()[0] if row.message else ""
            lines.append(
                f"- [{row.url_type}][{row.variant}][{row.form}] {row.name} :: "
                f"{_signature(row.message)} :: {first_line}"
            )

        lines.append("")
        lines.append("## Баг-репорт (RU)")
        lines.append("")
        lines.append("| Кейс | Шаги | Ожидаемый результат | Фактический результат | Описание бага |")
        lines.append("|---|---|---|---|---|")
        for row in sorted(failed_like, key=lambda r: (r.url_type, r.variant, r.form, r.name)):
            expected, actual, desc = _bug_details(row.message)
            case_name = _extract_case_name(row.name)
            steps = (
                f"URL `{row.url_type}`, форма `{row.form}`, вариант `{row.variant}`: "
                "пройти сценарий поиска адреса (улица -> дом -> проверки)."
            )
            lines.append(
                f"| {_md(case_name)} | {_md(steps)} | {_md(expected)} | {_md(actual)} | {_md(desc)} |"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize latest form-matrix Allure results.")
    parser.add_argument("--site", default="mts_internet_online")
    parser.add_argument("--allure-root", default="artifacts/allure-results")
    parser.add_argument(
        "--url-type",
        action="append",
        dest="url_types",
        help="Repeatable. If omitted, include all url_type folders for the site.",
    )
    parser.add_argument("--output", help="Optional markdown output file path.")
    args = parser.parse_args()

    site_root = Path(args.allure_root) / args.site
    if not site_root.exists():
        print(f"Site results directory does not exist: {site_root}")
        return 1

    url_types = set(args.url_types) if args.url_types else None
    rows = _latest(_load_rows(site_root, url_types))
    report = _render_markdown(rows)
    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\nSaved summary: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
