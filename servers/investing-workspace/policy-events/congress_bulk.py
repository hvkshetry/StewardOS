"""
Simple Congress.gov API client for bulk data retrieval.
No filtering - returns all data for LLM to analyze.
"""
import asyncio
import httpx
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = float(os.getenv("POLICY_EVENTS_HTTP_TIMEOUT_SEC", "30"))
DEFAULT_CONNECT_TIMEOUT_SEC = float(os.getenv("POLICY_EVENTS_CONNECT_TIMEOUT_SEC", "10"))
MAX_RETRIES = max(1, int(os.getenv("POLICY_EVENTS_MAX_RETRIES", "3")))
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
MAX_BILL_PAGES = max(1, int(os.getenv("CONGRESS_MAX_BILL_PAGES", "12")))
MAX_EMPTY_BILL_PAGES = max(1, int(os.getenv("CONGRESS_MAX_EMPTY_BILL_PAGES", "4")))
HEARING_DETAIL_CONCURRENCY = max(1, int(os.getenv("CONGRESS_HEARING_DETAIL_CONCURRENCY", "8")))


def _parse_iso_date(date_value: Optional[str]) -> Optional[datetime]:
    """Parse API date strings to UTC datetimes."""
    if not date_value:
        return None
    raw = date_value.strip()
    if not raw:
        return None
    if len(raw) == 10:
        raw = f"{raw}T00:00:00+00:00"
    elif raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_meeting_datetime(meeting: dict[str, Any]) -> Optional[datetime]:
    """Extract meeting datetime from sparse or hydrated committee-meeting payloads."""
    if not isinstance(meeting, dict):
        return None

    candidates = [
        meeting.get("date"),
        meeting.get("meetingDate"),
        meeting.get("meetingDateTime"),
        meeting.get("startDate"),
        meeting.get("startDateTime"),
    ]
    for value in candidates:
        parsed = _parse_iso_date(str(value) if value else None)
        if parsed is not None:
            return parsed
    return None


def get_current_congress() -> int:
    """Calculate current Congress number based on date.

    Congress changes every 2 years on January 3rd.
    119th Congress: 2025-2026
    118th Congress: 2023-2024
    """
    current_date = datetime.now()
    current_year = current_date.year

    # Congress starts on January 3rd of odd years.
    if current_date.month == 1 and current_date.day < 3 and current_year % 2 == 1:
        effective_year = current_year - 1
    else:
        effective_year = current_year

    # First Congress was 1789-1791; each Congress spans 2 years.
    return 1 + ((effective_year - 1789) // 2)


def _congress_candidates() -> list[int]:
    current = get_current_congress()
    return [current, current - 1, current - 2]


class CongressBulkClient:
    """Lightweight Congress.gov API client"""

    BASE_URL = "https://api.congress.gov/v3"

    def __init__(self):
        self.api_key = os.getenv("CONGRESS_API_KEY")
        self.session: httpx.AsyncClient | None = None
        self.timeout_sec = max(5.0, DEFAULT_TIMEOUT_SEC)
        self.connect_timeout_sec = max(2.0, min(DEFAULT_CONNECT_TIMEOUT_SEC, self.timeout_sec))
        self.max_retries = MAX_RETRIES

    def _validate_api_key(self) -> None:
        """Validate that API key is configured."""
        if not self.api_key:
            raise ValueError(
                "Missing CONGRESS_API_KEY environment variable. "
                "Get your free API key at https://api.congress.gov/sign-up/"
            )

    def _build_session(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            timeout=self.timeout_sec,
            connect=self.connect_timeout_sec,
            read=self.timeout_sec,
            write=self.timeout_sec,
        )
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        return httpx.AsyncClient(timeout=timeout, limits=limits)

    async def _ensure_session(self) -> None:
        if self.session is None:
            self.session = self._build_session()

    async def _close_session(self) -> None:
        if self.session is not None:
            await self.session.aclose()
            self.session = None

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_session()

    async def _request_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_session()
        assert self.session is not None

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.session.get(f"{self.BASE_URL}{endpoint}", params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries - 1:
                    delay = 0.4 * (2**attempt)
                    logger.warning(
                        "Congress.gov transient HTTP %s on %s (attempt %s/%s); retrying in %.1fs",
                        exc.response.status_code,
                        endpoint,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    delay = 0.4 * (2**attempt)
                    logger.warning(
                        "Congress.gov request error on %s (attempt %s/%s): %s; retrying in %.1fs",
                        endpoint,
                        attempt + 1,
                        self.max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise RuntimeError(f"Failed request for {endpoint}: {last_error}")

    async def get_recent_bills(
        self,
        days_back: int = 30,
        max_results: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Get all recent bills without filtering.
        Returns minimal metadata for LLM analysis.
        """
        self._validate_api_key()

        bills: list[dict[str, Any]] = []
        fallback_bills: list[dict[str, Any]] = []

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)
        current_congress = get_current_congress()
        min_congress = max(1, current_congress - 1)

        seen_keys: set[tuple[int | str | None, str]] = set()
        endpoint_sequence: list[tuple[str, bool]] = [
            (f"/bill/{current_congress}", False),
        ]
        if min_congress != current_congress:
            endpoint_sequence.append((f"/bill/{min_congress}", False))
        endpoint_sequence.append(("/bill", True))

        for endpoint, uses_datetime_window in endpoint_sequence:
            if len(bills) >= max_results:
                break
            # Only hit the broad endpoint if focused congress endpoints yielded nothing.
            if endpoint == "/bill" and bills:
                break

            offset = 0
            pages_fetched = 0
            empty_pages = 0
            while len(bills) < max_results and pages_fetched < MAX_BILL_PAGES:
                pages_fetched += 1
                before_count = len(bills)
                request_limit = min(max_results - len(bills), 250)
                params: dict[str, Any] = {
                    "limit": request_limit,
                    "offset": offset,
                    "format": "json",
                }
                if uses_datetime_window:
                    params["fromDateTime"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
                    params["toDateTime"] = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
                if self.api_key:
                    params["api_key"] = self.api_key

                try:
                    data = await self._request_json(endpoint, params)
                except httpx.HTTPStatusError as e:
                    logger.error("HTTP error fetching bills from %s: %s", endpoint, e)
                    if e.response.status_code in {401, 403}:
                        raise ValueError(
                            f"Congress.gov authentication error: {e.response.status_code}. "
                            "Verify your CONGRESS_API_KEY is valid at https://api.congress.gov/sign-up/"
                        ) from e
                    break
                except Exception as e:
                    logger.error("Error fetching bills from %s: %s", endpoint, e)
                    break

                page_rows = data.get("bills", [])
                if not isinstance(page_rows, list) or not page_rows:
                    break

                for bill in page_rows:
                    bill_congress_raw = bill.get("congress")
                    bill_congress: int | None
                    try:
                        bill_congress = int(bill_congress_raw) if bill_congress_raw is not None else None
                    except (TypeError, ValueError):
                        bill_congress = None
                    latest_action = bill.get("latestAction") or {}
                    if not isinstance(latest_action, dict):
                        latest_action = {}

                    update_date = bill.get("updateDate", "") or bill.get("updateDateIncludingText", "")
                    action_date = latest_action.get("actionDate", "")
                    parsed_update = _parse_iso_date(update_date)
                    parsed_action = _parse_iso_date(action_date)
                    filter_date = parsed_update or parsed_action
                    if filter_date is None:
                        continue
                    if filter_date < start_date or filter_date > end_date:
                        continue

                    sponsor_name = ""
                    sponsor_obj = bill.get("sponsor")
                    if isinstance(sponsor_obj, dict):
                        raw_name = sponsor_obj.get("fullName") or sponsor_obj.get("name")
                        sponsor_name = str(raw_name).strip() if raw_name else ""
                    elif isinstance(bill.get("sponsors"), list) and bill.get("sponsors"):
                        first_sponsor = bill["sponsors"][0]
                        if isinstance(first_sponsor, dict):
                            raw_name = first_sponsor.get("fullName") or first_sponsor.get("name")
                            sponsor_name = str(raw_name).strip() if raw_name else ""

                    row = {
                        "bill_id": f"{bill.get('type', '')}-{bill.get('number', '')}",
                        "congress": bill_congress if bill_congress is not None else bill.get("congress"),
                        "title": bill.get("title", ""),
                        "sponsor": sponsor_name,
                        "latest_action": latest_action.get("text", ""),
                        "action_date": action_date,
                        "update_date": update_date,
                        "url": bill.get("url", ""),
                        "_sort_ts": filter_date.timestamp(),
                    }
                    fallback_bills.append(dict(row))

                    # Keep primary results focused on current legislative context.
                    if bill_congress is not None and bill_congress < min_congress:
                        continue

                    dedupe_key = (row.get("congress"), row["bill_id"])
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    bills.append(row)

                    if len(bills) >= max_results:
                        break

                offset += len(page_rows)
                if len(page_rows) < request_limit:
                    break

                if len(bills) == before_count:
                    empty_pages += 1
                else:
                    empty_pages = 0
                if empty_pages >= MAX_EMPTY_BILL_PAGES:
                    logger.warning(
                        "Stopping Congress bill pagination on %s after %s consecutive pages with no in-range bills",
                        endpoint,
                        empty_pages,
                    )
                    break

            if pages_fetched >= MAX_BILL_PAGES and len(bills) < max_results:
                logger.warning(
                    "Reached Congress bill page cap (%s) on %s before collecting %s in-range bills",
                    MAX_BILL_PAGES,
                    endpoint,
                    max_results,
                )

        bills.sort(key=lambda row: row.get("_sort_ts", 0), reverse=True)
        trimmed: list[dict[str, Any]] = []
        for row in bills[:max_results]:
            row.pop("_sort_ts", None)
            trimmed.append(row)

        if not trimmed and fallback_bills:
            fallback_bills.sort(key=lambda row: row.get("_sort_ts", 0), reverse=True)
            for row in fallback_bills[:max_results]:
                row.pop("_sort_ts", None)
                trimmed.append(row)

        logger.info("Retrieved %s bills from Congress.gov", len(trimmed))
        return trimmed

    async def get_upcoming_hearings(
        self,
        days_ahead: int = 30,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get all upcoming hearings without filtering.
        Returns minimal metadata for LLM analysis.
        """
        self._validate_api_key()

        hearings: list[dict[str, Any]] = []
        today = datetime.now(timezone.utc).date()
        max_date = today + timedelta(days=days_ahead)
        sem = asyncio.Semaphore(HEARING_DETAIL_CONCURRENCY)

        async def hydrate_meeting(
            chamber: str,
            current_congress: int,
            base_params: dict[str, Any],
            meeting: dict[str, Any],
        ) -> dict[str, Any]:
            if not isinstance(meeting, dict):
                return {}
            meeting_payload = dict(meeting)
            event_id = meeting.get("eventId")
            if not event_id:
                return meeting_payload

            detail_endpoint = f"/committee-meeting/{current_congress}/{chamber}/{event_id}"
            try:
                async with sem:
                    detail_data = await self._request_json(detail_endpoint, base_params)
                detail_meeting = detail_data.get("committeeMeeting", {})
                if isinstance(detail_meeting, dict) and detail_meeting:
                    meeting_payload.update(detail_meeting)
            except Exception as exc:
                logger.debug(
                    "Could not hydrate hearing details for event_id=%s (%s chamber): %s",
                    event_id,
                    chamber,
                    exc,
                )

            return meeting_payload

        current_congress = get_current_congress()
        for chamber in ["house", "senate"]:
            endpoint = f"/committee-meeting/{current_congress}/{chamber}"
            params = {
                "limit": min(max(1, max_results), 250),
                "format": "json",
            }

            if self.api_key:
                params["api_key"] = self.api_key

            try:
                data = await self._request_json(endpoint, params)
            except Exception as e:
                logger.error("Error fetching %s hearings: %s", chamber, e)
                continue

            raw_meetings = data.get("committeeMeetings", [])
            if not isinstance(raw_meetings, list) or not raw_meetings:
                continue

            hydrated_rows = await asyncio.gather(
                *[
                    hydrate_meeting(chamber, current_congress, params, meeting)
                    for meeting in raw_meetings
                    if isinstance(meeting, dict)
                ]
            )

            for meeting_payload in hydrated_rows:
                parsed_date = _extract_meeting_datetime(meeting_payload)
                if parsed_date is None:
                    continue

                meeting_day = parsed_date.date()
                if meeting_day < today or meeting_day > max_date:
                    continue

                committee_name = ""
                committees = meeting_payload.get("committees", [])
                if isinstance(committees, list) and committees:
                    first = committees[0]
                    if isinstance(first, dict):
                        raw_name = first.get("name") or first.get("title") or ""
                        committee_name = str(raw_name).strip()
                    elif isinstance(first, str):
                        committee_name = first.strip()

                hearings.append(
                    {
                        "event_id": meeting_payload.get("eventId"),
                        "chamber": chamber.title(),
                        "title": meeting_payload.get("title", ""),
                        "committee": committee_name,
                        "date": parsed_date.isoformat(),
                        "time": meeting_payload.get("time", ""),
                        "location": meeting_payload.get("location", ""),
                        "congress": current_congress,
                        "url": meeting_payload.get("url", ""),
                    }
                )

                if len(hearings) >= max_results:
                    break

            if len(hearings) >= max_results:
                break

        logger.info("Retrieved %s hearings from Congress.gov", len(hearings))
        return hearings[:max_results]

    async def get_bill_details(self, bill_ids: List[str]) -> List[Dict[str, Any]]:
        """Get full details for specific bills identified by LLM."""
        self._validate_api_key()

        detailed_bills: list[dict[str, Any]] = []

        for bill_id in bill_ids:
            parts = bill_id.split("-")
            if len(parts) != 2:
                continue

            bill_type = parts[0].lower()
            bill_number = parts[1]

            bill: dict[str, Any] | None = None
            resolved_congress: int | None = None

            for congress in _congress_candidates():
                endpoint = f"/bill/{congress}/{bill_type}/{bill_number}"
                params = {"format": "json"}
                if self.api_key:
                    params["api_key"] = self.api_key

                try:
                    payload = await self._request_json(endpoint, params)
                    bill = payload.get("bill", {})
                    resolved_congress = congress
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        continue
                    logger.error("Error fetching details for %s: %s", bill_id, exc)
                    break
                except Exception as exc:
                    logger.error("Error fetching details for %s: %s", bill_id, exc)
                    break

            if bill is None or resolved_congress is None:
                continue

            params = {"format": "json"}
            if self.api_key:
                params["api_key"] = self.api_key

            committees_data: dict[str, Any] = {}
            text_data: dict[str, Any] = {}
            try:
                committees_endpoint = f"/bill/{resolved_congress}/{bill_type}/{bill_number}/committees"
                committees_data = await self._request_json(committees_endpoint, params)
            except Exception:
                committees_data = {}

            try:
                text_endpoint = f"/bill/{resolved_congress}/{bill_type}/{bill_number}/text"
                text_data = await self._request_json(text_endpoint, params)
            except Exception:
                text_data = {}

            detailed_bills.append(
                {
                    "bill_id": bill_id,
                    "title": bill.get("title", ""),
                    "summary": bill.get("summary", {}).get("text", "") if bill.get("summary") else "",
                    "sponsor": bill.get("sponsors", [{}])[0] if bill.get("sponsors") else {},
                    "cosponsors_count": bill.get("cosponsors", {}).get("count", 0),
                    "committees": committees_data.get("committees", []),
                    "actions": bill.get("actions", {}).get("item", [])[:10] if bill.get("actions") else [],
                    "text_versions": text_data.get("textVersions", []),
                    "congress": resolved_congress,
                    "congress_url": f"https://www.congress.gov/bill/{resolved_congress}th-congress/{bill_type.replace('res', '-resolution')}/{bill_number}",
                }
            )

        return detailed_bills

    async def get_hearing_details(self, event_ids: List[str]) -> List[Dict[str, Any]]:
        """Get full details for specific hearings identified by LLM."""
        self._validate_api_key()

        detailed_hearings: list[dict[str, Any]] = []

        for event_id in event_ids:
            found = False
            for congress in _congress_candidates():
                for chamber in ["house", "senate"]:
                    endpoint = f"/committee-meeting/{congress}/{chamber}/{event_id}"
                    params = {"format": "json"}
                    if self.api_key:
                        params["api_key"] = self.api_key

                    try:
                        data = await self._request_json(endpoint, params)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 404:
                            continue
                        logger.error("Error fetching details for %s in %s: %s", event_id, chamber, exc)
                        continue
                    except Exception as exc:
                        logger.error("Error fetching details for %s in %s: %s", event_id, chamber, exc)
                        continue

                    meeting = data.get("committeeMeeting", {})
                    if not isinstance(meeting, dict) or not meeting:
                        continue

                    detailed_hearings.append(
                        {
                            "event_id": event_id,
                            "chamber": chamber.title(),
                            "title": meeting.get("title", ""),
                            "committees": meeting.get("committees", []),
                            "date": meeting.get("date", ""),
                            "type": meeting.get("type", ""),
                            "witnesses": meeting.get("witnesses", []),
                            "documents": meeting.get("documents", []),
                            "congress": congress,
                            "url": f"https://www.congress.gov/committee-meeting/{congress}/{chamber}/{event_id}",
                        }
                    )
                    found = True
                    break

                if found:
                    break

        return detailed_hearings
