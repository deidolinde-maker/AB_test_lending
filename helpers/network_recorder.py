from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
from urllib.parse import parse_qs, urlparse


@dataclass
class NetworkEvent:
    case_id: str
    variant: str
    action: str | None
    method: str
    url: str
    query_params: dict[str, list[str]]
    status: int | None = None
    response_snippet: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NetworkRecorder:
    def __init__(self, page, *, case_id: str, variant: str) -> None:
        self.page = page
        self.case_id = case_id
        self.variant = variant
        self.events: list[NetworkEvent] = []

    def start(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def stop(self) -> None:
        self.page.remove_listener("request", self._on_request)
        self.page.remove_listener("response", self._on_response)

    def _on_request(self, request) -> None:
        url = request.url
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        action = (query_params.get("action") or [None])[0]
        is_search_like = action in {"cf7_proxy_streets", "cf7_proxy_houses"} or any(
            marker in parsed.path.lower()
            for marker in (
                "/search/",
                "/v2/streets",
                "/v2/houses",
                "/streets",
                "/houses",
                "/autocomplete",
                "/suggest",
                "/api_protected/",
                "/cf7proxy/",
                "/cf7proxy/v2/streets",
                "/cf7proxy/v2/houses",
            )
        )
        if not is_search_like:
            return
        self.events.append(
            NetworkEvent(
                case_id=self.case_id,
                variant=self.variant,
                action=action,
                method=request.method,
                url=url,
                query_params=query_params,
            )
        )

    def _on_response(self, response) -> None:
        url = response.url
        for event in reversed(self.events):
            if event.url == url and event.status is None:
                event.status = response.status
                try:
                    payload = response.text()
                    event.response_snippet = payload[:10000]
                except Exception:
                    event.response_snippet = None
                break

    @staticmethod
    def _safe_json_loads(text: str | None):
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _extract_search_records(payload) -> list[dict]:
        records: list[dict] = []
        seen: set[str] = set()

        def add(record: dict) -> None:
            key = json.dumps(record, sort_keys=True, ensure_ascii=False)
            if key in seen:
                return
            seen.add(key)
            records.append(record)

        def walk(node) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, dict):
                return

            data = node.get("data")
            if isinstance(data, dict):
                add(data)
                return
            if isinstance(data, list):
                for item in data:
                    walk(item)
                return

            if any(
                key in node
                for key in ("id", "street_name", "house", "street_id", "locality_id", "locality_name", "region_id")
            ):
                add(node)
                return

            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        walk(payload)
        return records

    @staticmethod
    def _record_preview(record: dict) -> dict:
        keys = ("id", "region_id", "street_id", "house", "street_name", "street_type", "locality_id", "locality_name")
        preview = {key: record.get(key) for key in keys if key in record}
        if "full" in record:
            preview["full"] = record.get("full")
        if "url" in record:
            preview["url"] = record.get("url")
        return preview

    @staticmethod
    def _norm_text(value: str | None) -> str:
        return " ".join((value or "").strip().lower().replace("ё", "е").split())

    @staticmethod
    def _norm_house(value: str | None) -> str:
        out = (value or "").lower().replace(" ", "")
        out = out.replace("корпус", "к")
        out = out.replace("к.", "к")
        out = out.replace("/", "к")
        return out

    def build_b_endpoint_summary(self) -> list[dict]:
        summary: list[dict] = []
        for event in self.events:
            if event.action not in {"cf7_proxy_streets", "cf7_proxy_houses"}:
                continue
            payload = self._safe_json_loads(event.response_snippet)
            records = self._extract_search_records(payload)
            payload_type = type(payload).__name__ if payload is not None else None
            payload_preview = None
            if isinstance(payload, dict):
                payload_preview = {k: type(v).__name__ for k, v in list(payload.items())[:8]}
            elif isinstance(payload, list):
                payload_preview = {
                    "list_size": len(payload),
                    "first_item_keys": list(payload[0].keys())[:8]
                    if payload and isinstance(payload[0], dict)
                    else None,
                }
            summary.append(
                {
                    "action": event.action,
                    "url": event.url,
                    "method": event.method,
                    "status": event.status,
                    "query_params": event.query_params,
                    "payload_type": payload_type,
                    "payload_preview": payload_preview,
                    "records": [self._record_preview(record) for record in records[:5]],
                    "response_snippet": event.response_snippet,
                }
            )
        return summary

    @staticmethod
    def _first_query_value(event: dict, key: str) -> str | None:
        values = event.get("query_params", {}).get(key) or []
        if not values:
            return None
        return str(values[0])

    def _assert_b_endpoint_payload(
        self,
        *,
        action: str,
        step_name: str,
        expected_region_id: int,
        expected_street: str | None = None,
        expected_house: str | None = None,
        expected_street_id: str | int | None = None,
    ) -> list[dict]:
        if self.variant != "B":
            return []
        deadline = time.monotonic() + 15
        last_summary: list[dict] = []

        def _build_summary() -> list[dict]:
            return [item for item in self.build_b_endpoint_summary() if item.get("action") == action]

        expected_parts = [f"region_id={expected_region_id!r}"]
        if expected_street is not None:
            expected_parts.append(f"street={expected_street!r}")
        if expected_house is not None:
            expected_parts.append(f"house={expected_house!r}")
        if expected_street_id is not None:
            expected_parts.append(f"street_id={expected_street_id!r}")
        expected_parts_text = ", ".join(expected_parts)

        while time.monotonic() < deadline:
            summary = _build_summary()
            last_summary = summary
            request_matches: list[dict] = []
            for item in summary:
                request_region_id = self._first_query_value(item, "region_id")
                request_query = self._first_query_value(item, "query")
                request_street_id = self._first_query_value(item, "street_id")

                if request_region_id is not None and str(request_region_id) != str(expected_region_id):
                    continue

                if action == "cf7_proxy_streets" and expected_street is not None:
                    if request_query is None or self._norm_text(request_query) != self._norm_text(expected_street):
                        continue
                if action == "cf7_proxy_houses" and expected_street_id is not None:
                    if request_street_id is None or str(request_street_id) != str(expected_street_id):
                        continue

                request_matches.append(item)

            if request_matches:
                def _match_record(record: dict) -> bool:
                    try:
                        record_region_id = int(record.get("region_id"))
                    except Exception:
                        return False
                    if record_region_id != int(expected_region_id):
                        return False
                    if expected_street is not None and self._norm_text(str(record.get("street_name", ""))) != self._norm_text(expected_street):
                        return False
                    if expected_house is not None and self._norm_house(str(record.get("house", ""))) != self._norm_house(expected_house):
                        return False
                    if expected_street_id is not None:
                        record_street_id = record.get("street_id")
                        if record_street_id is None:
                            return False
                        if str(record_street_id) != str(expected_street_id):
                            return False
                    return True

                observed_records: list[dict] = []
                for item in request_matches:
                    observed_records.extend(item.get("records") or [])

                matched_records = [record for record in observed_records if _match_record(record)]
                if matched_records:
                    return matched_records

            time.sleep(0.25)

        raise AssertionError(
            f"Step: {step_name}\n"
            "Error code: search_payload_mismatch\n"
            f"Expected: search payload should resolve the selected address record ({expected_parts_text})\n"
            f"Actual: observed search payloads = {[{'action': item.get('action'), 'url': item.get('url'), 'query_params': item.get('query_params'), 'records': item.get('records') or []} for item in last_summary]}"
        )

    def assert_b_street_payload(
        self,
        *,
        expected_street: str,
        expected_region_id: int,
    ) -> list[dict]:
        return self._assert_b_endpoint_payload(
            action="cf7_proxy_streets",
            step_name="Validate B street payload",
            expected_region_id=expected_region_id,
            expected_street=expected_street,
        )

    def assert_b_house_payload(
        self,
        *,
        expected_house: str,
        expected_region_id: int,
        expected_street_id: str | int | None = None,
    ) -> list[dict]:
        return self._assert_b_endpoint_payload(
            action="cf7_proxy_houses",
            step_name="Validate B house payload",
            expected_region_id=expected_region_id,
            expected_house=expected_house,
            expected_street_id=expected_street_id,
        )

    def assert_b_search_payload(
        self,
        *,
        expected_street: str,
        expected_house: str,
        expected_region_id: int,
    ) -> list[dict]:
        self.assert_b_street_payload(expected_street=expected_street, expected_region_id=expected_region_id)
        # Backward-compatible combined assertion for older callers.
        return self.assert_b_house_payload(
            expected_house=expected_house,
            expected_region_id=expected_region_id,
        )

    def _format_observed_search_urls(self, limit: int = 12) -> list[str]:
        observed: list[str] = []
        seen: set[str] = set()
        for event in self.events:
            url = event.url
            if url in seen:
                continue
            seen.add(url)
            observed.append(url)
            if len(observed) >= limit:
                break
        return observed
