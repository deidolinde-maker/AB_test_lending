from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlparse


@dataclass
class NetworkEvent:
    case_id: str
    variant: str
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
        path = parsed.path.lower()
        is_search_like = any(
            marker in path
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
                method=request.method,
                url=url,
                query_params=parse_qs(parsed.query),
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

    def build_b_endpoint_summary(self) -> list[dict]:
        summary: list[dict] = []
        for event in self.events:
            payload = self._safe_json_loads(event.response_snippet)
            records = self._extract_search_records(payload)
            if not records:
                continue
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

    def assert_b_search_payload(
        self,
        *,
        expected_street: str,
        expected_house: str,
        expected_region_id: int,
    ) -> None:
        if self.variant != "B":
            return
        summary = self.build_b_endpoint_summary()
        observed_records: list[dict] = []
        for item in summary:
            observed_records.extend(item.get("records") or [])

        def _match(record: dict) -> bool:
            try:
                record_region_id = int(record.get("region_id"))
            except Exception:
                return False
            if record_region_id != int(expected_region_id):
                return False
            if str(record.get("street_name", "")).strip() != str(expected_street).strip():
                return False
            if str(record.get("house", "")).strip() != str(expected_house).strip():
                return False
            return True

        if any(_match(record) for record in observed_records):
            return

        raise AssertionError(
            "Step: Validate B search payload\n"
            "Error code: search_payload_mismatch\n"
            "Expected: search payload should resolve the selected address record "
            f"(region_id={expected_region_id!r}, street={expected_street!r}, "
            f"house={expected_house!r})\n"
            f"Actual: observed search payloads = {[{'url': item.get('url'), 'records': item.get('records') or []} for item in summary]}"
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
