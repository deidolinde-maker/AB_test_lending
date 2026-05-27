from dataclasses import dataclass


@dataclass(frozen=True)
class SynonymRule:
    canonical: str
    aliases: list[str]


@dataclass(frozen=True)
class SynonymCase:
    case_id: str
    site: str
    url_type: str
    form: str
    variant: str
    region: str
    region_id: int
    canonical: str
    alias: str
    street_query: str
    expected_street: str
    house_query: str
    expected_house: str
    expected_id: int
    expected_id_type: str
    dataset: str = "synonyms"

    @property
    def pytest_id(self) -> str:
        return f"{self.site}__{self.url_type}__{self.form}__{self.variant}__{self.case_id}"

