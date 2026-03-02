"""
Simple GovInfo API client for bulk data retrieval.
No filtering - returns all data for LLM to analyze.
"""
import asyncio
import httpx
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = float(os.getenv("POLICY_EVENTS_HTTP_TIMEOUT_SEC", "30"))
DEFAULT_CONNECT_TIMEOUT_SEC = float(os.getenv("POLICY_EVENTS_CONNECT_TIMEOUT_SEC", "10"))
MAX_RETRIES = max(1, int(os.getenv("POLICY_EVENTS_MAX_RETRIES", "3")))
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


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


def _extract_offset_mark(next_page: str | None) -> str | None:
    if not next_page:
        return None
    parsed = urlparse(next_page)
    query = parse_qs(parsed.query)
    marks = query.get("offsetMark")
    if not marks:
        return None
    value = marks[0].strip()
    return value or None


class GovInfoBulkClient:
    """Lightweight GovInfo API client"""

    BASE_URL = "https://api.govinfo.gov"

    def __init__(self):
        self.api_key = os.getenv("GOVINFO_API_KEY")
        self.session: httpx.AsyncClient | None = None
        self.timeout_sec = max(5.0, DEFAULT_TIMEOUT_SEC)
        self.connect_timeout_sec = max(2.0, min(DEFAULT_CONNECT_TIMEOUT_SEC, self.timeout_sec))
        self.max_retries = MAX_RETRIES

    def _validate_api_key(self):
        """Validate that API key is configured"""
        if not self.api_key:
            raise ValueError(
                "Missing GOVINFO_API_KEY environment variable. "
                "Get your free API key at https://www.govinfo.gov/api-signup/"
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
                        "GovInfo transient HTTP %s on %s (attempt %s/%s); retrying in %.1fs",
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
                        "GovInfo request error on %s (attempt %s/%s): %s; retrying in %.1fs",
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

    async def _request_absolute_json(self, url: str) -> dict[str, Any]:
        await self._ensure_session()
        assert self.session is not None

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.session.get(url)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries - 1:
                    delay = 0.4 * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    delay = 0.4 * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise

        raise RuntimeError(f"Failed request for {url}: {last_error}")

    async def _collect_granules(self, package_id: str, remaining: int) -> list[dict[str, Any]]:
        """Collect granules for one Federal Register package (with pagination)."""
        if remaining <= 0:
            return []

        granules: list[dict[str, Any]] = []
        offset_mark = "*"

        while len(granules) < remaining:
            page_size = min(remaining - len(granules), 100)
            params = {
                "offsetMark": offset_mark,
                "pageSize": page_size,
            }
            if self.api_key:
                params["api_key"] = self.api_key

            payload = await self._request_json(f"/packages/{package_id}/granules", params)
            rows = payload.get("granules", [])
            if not isinstance(rows, list) or not rows:
                break

            granules.extend([row for row in rows if isinstance(row, dict)])
            if len(rows) < page_size:
                break

            next_mark = _extract_offset_mark(payload.get("nextPage"))
            if not next_mark or next_mark == offset_mark:
                break
            offset_mark = next_mark

        return granules

    async def get_federal_rules(
        self,
        days_back: int = 30,
        days_ahead: int = 30,
        max_results: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Get all Federal Register documents in date range.
        Returns minimal metadata for LLM analysis.
        """
        self._validate_api_key()

        rules: list[dict[str, Any]] = []

        start_dt = datetime.now(timezone.utc) - timedelta(days=days_back)
        end_dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        endpoint = f"/published/{start_date}/{end_date}"
        offset_mark = "*"

        try:
            while len(rules) < max_results:
                params = {
                    "collection": "FR",
                    "offsetMark": offset_mark,
                    "pageSize": 50,
                }
                if self.api_key:
                    params["api_key"] = self.api_key

                data = await self._request_json(endpoint, params)
                packages = data.get("packages", [])
                if not isinstance(packages, list) or not packages:
                    break

                for package in packages:
                    if not isinstance(package, dict):
                        continue

                    package_id = package.get("packageId", "")
                    if not (package_id and package_id.startswith("FR-") and len(package_id.split("-")) == 4):
                        continue

                    remaining = max_results - len(rules)
                    granule_rows = await self._collect_granules(package_id, remaining)
                    for granule in granule_rows:
                        title = granule.get("title", "")
                        title_lower = title.lower()

                        if "proposed rule" in title_lower:
                            rule_type = "Proposed Rule"
                        elif "final rule" in title_lower:
                            rule_type = "Final Rule"
                        elif "notice" in title_lower:
                            rule_type = "Notice"
                        else:
                            rule_type = "Other"

                        agency_names = self._normalize_agencies(granule.get("agencies"))
                        if not agency_names:
                            agency_names = self._normalize_agencies(package.get("agencies"))
                        if agency_names:
                            agency = ", ".join(agency_names)
                        else:
                            agency = "Unknown Agency"
                            if "-" in title:
                                agency = title.split("-")[0].strip()

                        rules.append(
                            {
                                "document_number": granule.get("granuleId", ""),
                                "title": title[:200],
                                "agency": agency,
                                "rule_type": rule_type,
                                "publication_date": package.get("dateIssued", ""),
                                "fr_url": granule.get("granuleLink", ""),
                                "package_id": package_id,
                            }
                        )

                        if len(rules) >= max_results:
                            break

                    if len(rules) >= max_results:
                        break

                if len(rules) >= max_results:
                    break

                next_mark = _extract_offset_mark(data.get("nextPage"))
                if not next_mark or next_mark == offset_mark:
                    break
                offset_mark = next_mark

            strict_rules: list[dict[str, Any]] = []
            for rule in rules:
                parsed = _parse_iso_date(rule.get("publication_date"))
                if parsed is None:
                    continue
                if parsed < start_dt or parsed > end_dt:
                    continue
                strict_rules.append(rule)

            logger.info("Retrieved %s Federal Register documents", len(strict_rules))
            return strict_rules[:max_results]

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching Federal Register documents: %s", e)
            if e.response.status_code in {401, 403}:
                raise ValueError(
                    f"GovInfo authentication error: {e.response.status_code}. "
                    "Verify your GOVINFO_API_KEY is valid at https://www.govinfo.gov/api-signup/"
                ) from e
            raise ValueError(
                f"GovInfo upstream error: HTTP {e.response.status_code}. "
                "The API may be unavailable or rate-limited; retry shortly."
            ) from e
        except Exception as e:
            logger.error("Error fetching Federal Register documents: %s", e)
            raise ValueError(f"Failed to fetch Federal Register documents from GovInfo: {str(e)}") from e

    async def _get_package_summary(self, package_id: str) -> Dict[str, Any]:
        """Get summary for a specific package."""
        try:
            endpoint = f"/packages/{package_id}/summary"
            params: dict[str, Any] = {}
            if self.api_key:
                params["api_key"] = self.api_key
            return await self._request_json(endpoint, params)
        except Exception as e:
            logger.error("Error fetching package summary for %s: %s", package_id, e)
            return {}

    def _extract_agency(self, summary: Dict[str, Any]) -> str:
        """Extract agency name from package summary."""
        agency = summary.get("agency", "")
        if not agency:
            agency = summary.get("issuingAgency", "")
        if not agency:
            title = summary.get("title", "")
            if "EPA" in title:
                agency = "Environmental Protection Agency"
            elif "SEC" in title:
                agency = "Securities and Exchange Commission"
            elif "FDA" in title:
                agency = "Food and Drug Administration"
            else:
                agency = "Unknown Agency"
        return agency

    def _normalize_agencies(self, raw_agencies: Any) -> List[str]:
        """Normalize agency payloads from GovInfo/Federal Register APIs."""
        if not raw_agencies:
            return []

        agencies: list[str] = []
        if isinstance(raw_agencies, list):
            for item in raw_agencies:
                if isinstance(item, str):
                    candidate = item.strip()
                elif isinstance(item, dict):
                    candidate = str(
                        item.get("name")
                        or item.get("raw_name")
                        or item.get("short_name")
                        or ""
                    ).strip()
                else:
                    candidate = ""
                if candidate:
                    agencies.append(candidate)
        elif isinstance(raw_agencies, str):
            candidate = raw_agencies.strip()
            if candidate:
                agencies.append(candidate)

        return list(dict.fromkeys(agencies))

    def _determine_rule_type(self, summary: Dict[str, Any]) -> str:
        """Determine if proposed, final, or notice."""
        doc_type = summary.get("documentType", "").lower()
        title = summary.get("title", "").lower()

        if "proposed" in doc_type or "proposed" in title:
            return "Proposed Rule"
        if "final" in doc_type or "final" in title:
            return "Final Rule"
        if "notice" in doc_type or "notice" in title:
            return "Notice"
        return "Other"

    async def get_rule_details(self, document_numbers: List[str]) -> List[Dict[str, Any]]:
        """
        Get full details for specific rules identified by LLM.
        Enhanced to fetch content from Federal Register API when available.
        Document numbers can be either:
        - Granule IDs (e.g., "2025-15325")
        - Package IDs with granule (e.g., "FR-2025-08-12:2025-15325")
        """
        self._validate_api_key()

        detailed_rules: list[dict[str, Any]] = []

        for doc_num in document_numbers:
            try:
                if ":" in doc_num:
                    package_id, granule_id = doc_num.split(":", 1)
                else:
                    granule_id = doc_num

                    fr_api_url = f"https://www.federalregister.gov/api/v1/documents/{granule_id}"
                    try:
                        fr_data = await self._request_absolute_json(fr_api_url)
                        agency_names = self._normalize_agencies(fr_data.get("agencies"))
                        detailed_rules.append(
                            {
                                "document_number": granule_id,
                                "title": fr_data.get("title", ""),
                                "agency": ", ".join(agency_names) if agency_names else "Unknown",
                                "rule_type": fr_data.get("type", "Unknown"),
                                "publication_date": fr_data.get("publication_date", ""),
                                "effective_date": fr_data.get("effective_on", ""),
                                "comment_close_date": fr_data.get("comments_close_on", ""),
                                "abstract": fr_data.get("abstract", ""),
                                "summary": fr_data.get("abstract", "") or fr_data.get("action", "") or fr_data.get("title", ""),
                                "significant": fr_data.get("significant", False),
                                "cfr_references": fr_data.get("cfr_references", []),
                                "docket_ids": fr_data.get("docket_ids", []),
                                "pdf_link": fr_data.get("pdf_url", ""),
                                "html_link": fr_data.get("html_url", ""),
                                "fr_url": fr_data.get("html_url", f"https://www.federalregister.gov/d/{granule_id}"),
                            }
                        )
                        continue
                    except Exception as e:
                        logger.warning("Failed to fetch from Federal Register API for %s: %s", granule_id, e)

                    detailed_rules.append(
                        {
                            "document_number": granule_id,
                            "title": f"Federal Register Document {granule_id}",
                            "agency": "Various",
                            "rule_type": "See document",
                            "publication_date": "Recent",
                            "effective_date": "See document for effective date",
                            "comment_close_date": "See document for comment deadline",
                            "summary": f"Document {granule_id} from Federal Register. For full details, visit federalregister.gov",
                            "pdf_link": f"https://www.federalregister.gov/documents/search?conditions%5Bterm%5D={granule_id}",
                            "text_link": "",
                            "fr_url": f"https://www.federalregister.gov/d/{granule_id}",
                        }
                    )
                    continue

                endpoint = f"/packages/{package_id}/granules/{granule_id}/summary"
                params: dict[str, Any] = {}
                if self.api_key:
                    params["api_key"] = self.api_key

                data = await self._request_json(endpoint, params)
                package_agencies = self._normalize_agencies(data.get("agencies"))
                detailed_rules.append(
                    {
                        "document_number": granule_id,
                        "title": data.get("title", ""),
                        "agency": package_agencies[0] if package_agencies else "Unknown",
                        "rule_type": data.get("documentType", "Unknown"),
                        "publication_date": data.get("dateIssued", ""),
                        "effective_date": data.get("effectiveDate", ""),
                        "comment_close_date": self._extract_comment_date(data),
                        "summary": data.get("abstract", "") or data.get("summary", ""),
                        "pdf_link": data.get("download", {}).get("pdfLink", ""),
                        "text_link": data.get("download", {}).get("txtLink", ""),
                        "fr_url": data.get("detailsLink", ""),
                    }
                )

            except Exception as e:
                logger.error("Error fetching details for %s: %s", doc_num, e)
                continue

        return detailed_rules

    def _extract_comment_date(self, summary: Dict[str, Any]) -> Optional[str]:
        """Extract comment close date if present."""
        if "commentCloseDate" in summary:
            return summary["commentCloseDate"]

        summary_text = summary.get("summary", "").lower()
        if "comments must be received" in summary_text or "comment period" in summary_text:
            return "See document for comment deadline"

        return None
