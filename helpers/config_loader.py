from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

from models import FormConfig, SearchCase, SiteConfig, SynonymRule


@dataclass(frozen=True)
class LoadedConfig:
    sites: list[SiteConfig]
    forms: list[FormConfig]
    addresses: list[dict[str, Any]]
    forbidden_region_cases: list[dict[str, Any]]
    synonym_rules: list[SynonymRule]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file is missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = fh.read()
    if yaml is not None:
        data = yaml.safe_load(raw) or {}
    else:
        data = _safe_yaml_subset_parse(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Top-level YAML object must be dict: {path}")
    return data


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:idx].rstrip()
    return line.rstrip()


def _parse_scalar(value: str) -> Any:
    trimmed = value.strip()
    if trimmed in {"null", "Null", "NULL", "~"}:
        return None
    if trimmed in {"true", "True"}:
        return True
    if trimmed in {"false", "False"}:
        return False
    if trimmed.startswith('"') and trimmed.endswith('"'):
        return trimmed[1:-1]
    if trimmed.startswith("'") and trimmed.endswith("'"):
        return trimmed[1:-1]
    if trimmed.isdigit():
        return int(trimmed)
    return trimmed


def _parse_key_value(chunk: str) -> tuple[str, Any, bool]:
    key, _, tail = chunk.partition(":")
    key = key.strip()
    tail = tail.strip()
    if tail == "":
        return key, None, True
    return key, _parse_scalar(tail), False


def _safe_yaml_subset_parse(text: str) -> dict[str, Any]:
    prepared: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        cleaned = _strip_comment(raw_line)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        prepared.append((indent, cleaned.lstrip(" ")))

    idx = 0

    def parse_block(expected_indent: int):
        nonlocal idx
        container = None

        while idx < len(prepared):
            indent, content = prepared[idx]
            if indent < expected_indent:
                break
            if indent > expected_indent:
                raise ValueError(f"Invalid indentation near: {content}")

            if content.startswith("- "):
                if container is None:
                    container = []
                if not isinstance(container, list):
                    raise ValueError(f"Expected list item but got mapping near: {content}")
                item_content = content[2:].strip()
                idx += 1

                if item_content == "":
                    container.append(parse_block(expected_indent + 2))
                    continue

                if ":" in item_content:
                    item_dict: dict[str, Any] = {}
                    key, value, needs_nested = _parse_key_value(item_content)
                    if needs_nested:
                        item_dict[key] = parse_block(expected_indent + 2)
                    else:
                        item_dict[key] = value

                    while idx < len(prepared):
                        next_indent, next_content = prepared[idx]
                        if next_indent < expected_indent + 2 or next_content.startswith("- "):
                            break
                        if next_indent != expected_indent + 2:
                            raise ValueError(f"Invalid list item indentation near: {next_content}")
                        sub_key, sub_value, sub_nested = _parse_key_value(next_content)
                        idx += 1
                        if sub_nested:
                            item_dict[sub_key] = parse_block(expected_indent + 4)
                        else:
                            item_dict[sub_key] = sub_value
                    container.append(item_dict)
                    continue

                container.append(_parse_scalar(item_content))
                continue

            if container is None:
                container = {}
            if not isinstance(container, dict):
                raise ValueError(f"Expected mapping item but got list near: {content}")

            key, value, needs_nested = _parse_key_value(content)
            idx += 1
            if needs_nested:
                container[key] = parse_block(expected_indent + 2)
            else:
                container[key] = value

        return container if container is not None else {}

    parsed = parse_block(0)
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a mapping")
    return parsed


def _validate_required_keys(data: dict[str, Any], keys: list[str], file_name: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        missing_joined = ", ".join(missing)
        raise ValueError(f"{file_name} is missing required keys: {missing_joined}")


def load_config(config_dir: str | Path = "config") -> LoadedConfig:
    config_path = Path(config_dir)
    sites_yaml = _read_yaml(config_path / "sites.yaml")
    forms_yaml = _read_yaml(config_path / "forms.yaml")
    search_data_yaml = _read_yaml(config_path / "search_data.yaml")
    synonyms_yaml = _read_yaml(config_path / "synonyms.yaml")

    _validate_required_keys(sites_yaml, ["sites"], "sites.yaml")
    _validate_required_keys(forms_yaml, ["forms"], "forms.yaml")
    _validate_required_keys(search_data_yaml, ["addresses", "forbidden_region_cases"], "search_data.yaml")
    _validate_required_keys(synonyms_yaml, ["rules"], "synonyms.yaml")

    sites: list[SiteConfig] = []
    for site_name, site_data in sites_yaml["sites"].items():
        if not site_data.get("enabled", False):
            continue
        sites.append(
            SiteConfig(
                name=site_name,
                title=site_data["title"],
                enabled=site_data["enabled"],
                urls=site_data["urls"],
                expected_regions=site_data.get("expected_regions", {}),
                allowed_region_pool=site_data.get("allowed_region_pool", []),
                regional_navigation_chain=site_data.get("regional_navigation_chain", []),
                required_forms_by_url_type=site_data.get("required_forms_by_url_type", {}),
            )
        )

    forms: list[FormConfig] = []
    for form_name, form_data in forms_yaml["forms"].items():
        if form_name == "business":
            continue
        if not form_data.get("participates_in_ab_search_iteration_1", False):
            continue
        forms.append(
            FormConfig(
                name=form_name,
                site_title=form_data.get("site_title", ""),
                participates_in_ab_search_iteration_1=form_data["participates_in_ab_search_iteration_1"],
                optional=form_data.get("optional", False),
                selectors=form_data.get("selectors", {}),
                behavior=form_data.get("behavior", {}),
            )
        )

    synonym_rules = [
        SynonymRule(canonical=rule["canonical"], aliases=rule.get("aliases", []))
        for rule in synonyms_yaml["rules"]
    ]

    return LoadedConfig(
        sites=sites,
        forms=forms,
        addresses=search_data_yaml["addresses"],
        forbidden_region_cases=search_data_yaml["forbidden_region_cases"],
        synonym_rules=synonym_rules,
    )


def build_search_case(
    raw_case: dict[str, Any],
    *,
    site: str,
    url_type: str,
    form: str,
    dataset: str,
) -> SearchCase:
    region = raw_case.get("region", raw_case.get("forbidden_region", ""))
    region_id = raw_case.get("region_id", raw_case.get("forbidden_region_id", 0))
    return SearchCase(
        case_id=raw_case["case_id"],
        site=site,
        url_type=url_type,
        form=form,
        variant=raw_case["variant"],
        region=region,
        region_id=region_id,
        street_query=raw_case["street_query"],
        expected_street=raw_case["expected_street"],
        house_query=raw_case["house_query"],
        expected_house=raw_case["expected_house"],
        expected_id=int(raw_case["expected_id"]),
        expected_id_type=raw_case["expected_id_type"],
        address_source=raw_case["address_source"],
        dataset=dataset,
        is_adjacent=bool(raw_case.get("is_adjacent", False)),
        expected_result=raw_case.get("expected_result", "found"),
    )
