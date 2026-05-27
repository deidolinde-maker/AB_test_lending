from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from helpers.config_loader import LoadedConfig, build_search_case
from models import SearchCase, SynonymCase


@dataclass(frozen=True)
class SiteUrlCase:
    site: str
    url_type: str

    @property
    def pytest_id(self) -> str:
        return f"{self.site}__{self.url_type}"


@dataclass(frozen=True)
class RegionalNavigationCase:
    site: str
    variant: str
    start_url_type: str

    @property
    def pytest_id(self) -> str:
        return f"{self.site}__regional_navigation__{self.variant}"


def _all_site_url_types(config: LoadedConfig) -> list[SiteUrlCase]:
    cases: list[SiteUrlCase] = []
    for site in config.sites:
        for url_type in site.urls:
            cases.append(SiteUrlCase(site=site.name, url_type=url_type))
    return cases


def _base_cases_for_variant(config: LoadedConfig, variant: str) -> list[dict]:
    return [raw for raw in config.addresses if raw["variant"] == variant]


def _expand_across_dimensions(config: LoadedConfig, raw_cases: Iterable[dict], dataset: str) -> list[SearchCase]:
    expanded: list[SearchCase] = []
    for raw in raw_cases:
        for site in config.sites:
            for url_type in site.urls:
                for form in config.forms:
                    expanded.append(
                        build_search_case(
                            raw,
                            site=site.name,
                            url_type=url_type,
                            form=form.name,
                            dataset=dataset,
                        )
                    )
    return expanded


def main_search_cases(config: LoadedConfig, variant: str) -> list[SearchCase]:
    raw_cases = _base_cases_for_variant(config, variant)
    return _expand_across_dimensions(config, raw_cases, "main_search")


def forbidden_region_cases(config: LoadedConfig, variant: str | None = None) -> list[SearchCase]:
    raw_cases = config.forbidden_region_cases
    if variant in {"A", "B"}:
        raw_cases = [raw for raw in raw_cases if raw["variant"] == variant]
    return _expand_across_dimensions(config, raw_cases, "forbidden_region")


def isolation_cases(config: LoadedConfig, variant: str) -> list[SearchCase]:
    opposite_variant = "B" if variant == "A" else "A"
    raw_cases = _base_cases_for_variant(config, opposite_variant)
    cases = _expand_across_dimensions(config, raw_cases, "isolation")
    return [SearchCase(**{**case.__dict__, "variant": variant}) for case in cases]


def adjacent_cases(config: LoadedConfig) -> list[SearchCase]:
    base = _expand_across_dimensions(config, config.addresses, "adjacent")
    return [
        SearchCase(
            **{**case.__dict__, "is_adjacent": True}
        )
        for case in base
    ]


def region_change_cases(config: LoadedConfig) -> list[SearchCase]:
    base = _expand_across_dimensions(config, config.addresses, "region_change")
    return base


def regional_navigation_cases(config: LoadedConfig, variant: str | None = None) -> list[RegionalNavigationCase]:
    variants = [variant] if variant in {"A", "B"} else ["A", "B"]
    cases: list[RegionalNavigationCase] = []
    for site in config.sites:
        for chosen in variants:
            cases.append(
                RegionalNavigationCase(
                    site=site.name,
                    variant=chosen,
                    start_url_type="domain_without_region",
                )
            )
    return cases


def synonym_cases(config: LoadedConfig) -> list[SynonymCase]:
    generated: list[SynonymCase] = []
    for raw in config.addresses:
        for site in config.sites:
            for url_type in site.urls:
                for form in config.forms:
                    for rule in config.synonym_rules:
                        canonical = rule.canonical
                        if canonical.isdigit():
                            continue
                        canonical_in_street = canonical.lower() in raw["expected_street"].lower()
                        canonical_in_house = canonical.lower() in raw["expected_house"].lower()
                        is_street_type_rule = canonical.lower() == "улица"
                        if not canonical_in_street and not canonical_in_house and not is_street_type_rule:
                            continue
                        for alias in rule.aliases[:1]:
                            if canonical_in_street:
                                street_query = raw["expected_street"].replace(canonical, alias)
                            elif is_street_type_rule:
                                # Keep the address grounded in real dataset streets by adding only
                                # a street-type synonym prefix (e.g. "ул Алабяна").
                                street_query = f"{alias} {raw['street_query']}"
                            else:
                                street_query = raw["street_query"]
                            house_query = raw["house_query"]
                            if canonical_in_house:
                                house_query = raw["expected_house"].replace(canonical, alias)
                            generated.append(
                                SynonymCase(
                                    case_id=f"{raw['case_id']}__{canonical}__{alias}",
                                    site=site.name,
                                    url_type=url_type,
                                    form=form.name,
                                    variant=raw["variant"],
                                    region=raw["region"],
                                    region_id=int(raw["region_id"]),
                                    canonical=canonical,
                                    alias=alias,
                                    street_query=street_query,
                                    expected_street=raw["expected_street"],
                                    house_query=house_query,
                                    expected_house=raw["expected_house"],
                                    expected_id=int(raw["expected_id"]),
                                    expected_id_type=raw["expected_id_type"],
                                )
                            )
    return generated


def ab_cookie_cases(config: LoadedConfig) -> list[SiteUrlCase]:
    return _all_site_url_types(config)
