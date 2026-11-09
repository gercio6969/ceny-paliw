"""Klient publicznego API ELI Sejmu (https://api.sejm.gov.pl/eli)."""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import date

import requests
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api.sejm.gov.pl/eli"
PUBLISHER = "MP"  # Monitor Polski
TITLE_QUERY = "maksymalnej ceny paliw"
_TITLE_RE = re.compile(r"maksymaln\w*\s+cen\w*\s+paliw", re.IGNORECASE)
USER_AGENT = "ceny-paliw/1.0 (+https://github.com/gercio6969/ceny-paliw)"
TIMEOUT = 30

# Limity chroniące przed nieoczekiwanie dużymi lub złośliwymi odpowiedziami.
MAX_JSON_BYTES = 5 * 1024 * 1024  # lista aktów z całego roku to kilkaset kB
MAX_PDF_BYTES = 5 * 1024 * 1024  # obwieszczenie to jedna strona, ~100 kB
MAX_PDF_PAGES = 5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActRef:
    """Pozycja aktu w Monitorze Polskim zwrócona przez API."""

    eli: str
    year: int
    position: int
    title: str
    announced: date | None

    @property
    def pdf_url(self) -> str:
        return f"{BASE_URL}/acts/{PUBLISHER}/{self.year}/{self.position}/text.pdf"


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _to_ref(item: dict) -> ActRef | None:
    title = str(item.get("title", ""))
    if not _TITLE_RE.search(title):
        return None
    try:
        year = int(item["year"])
        position = int(item["pos"])
    except (KeyError, TypeError, ValueError):
        return None
    announced = _parse_date(item.get("promulgation")) or _parse_date(item.get("announcementDate"))
    return ActRef(
        eli=str(item.get("ELI") or f"{PUBLISHER}/{year}/{position}"),
        year=year,
        position=position,
        title=title,
        announced=announced,
    )


def select_notices(items: list[dict]) -> list[ActRef]:
    """Filtruje obwieszczenia o cenach paliw i sortuje od najnowszego."""
    refs = {ref.eli: ref for item in items if (ref := _to_ref(item)) is not None}
    return sorted(refs.values(), key=lambda r: (r.year, r.position), reverse=True)


class ResponseTooLarge(ValueError):
    """Odpowiedź przekroczyła dopuszczalny rozmiar."""


def fetch_limited(
    session: requests.Session,
    url: str,
    *,
    max_bytes: int,
    params: dict | None = None,
    headers: dict | None = None,
) -> bytes:
    """GET z limitem rozmiaru – nie wczytuje do pamięci więcej niż ``max_bytes``."""
    with session.get(url, params=params, headers=headers, timeout=TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ResponseTooLarge(f"{url}: {declared} B > {max_bytes} B")
        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > max_bytes:
                raise ResponseTooLarge(f"{url}: ponad {max_bytes} B")
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_json(session: requests.Session, url: str, params: dict | None = None) -> object:
    raw = fetch_limited(
        session, url, max_bytes=MAX_JSON_BYTES, params=params,
        headers={"Accept": "application/json"},
    )  # fmt: skip
    return json.loads(raw)


def _get_items(session: requests.Session, url: str, params: dict | None = None) -> list[dict]:
    payload = fetch_json(session, url, params)
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"Nieoczekiwana odpowiedź API z {url}")
    return items


def find_notices(session: requests.Session, year: int) -> list[ActRef]:
    """Lista obwieszczeń o maksymalnej cenie paliw z danego roku, od najnowszego."""
    try:
        items = _get_items(
            session,
            f"{BASE_URL}/acts/search",
            {"publisher": PUBLISHER, "year": year, "title": TITLE_QUERY, "limit": 500},
        )
        notices = select_notices(items)
        if notices:
            return notices
        log.warning("Wyszukiwarka API nie zwróciła obwieszczeń za %s, pobieram pełną listę", year)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Wyszukiwarka API zawiodła (%s), pobieram pełną listę roku", exc)

    return select_notices(_get_items(session, f"{BASE_URL}/acts/{PUBLISHER}/{year}"))


def download_pdf_text(session: requests.Session, url: str) -> str:
    """Pobiera PDF (z limitem rozmiaru i stron) i zwraca jego tekst."""
    raw = fetch_limited(
        session, url, max_bytes=MAX_PDF_BYTES, headers={"Accept": "application/pdf"}
    )
    if not raw.startswith(b"%PDF-"):
        raise ValueError(f"{url}: odpowiedź nie jest plikiem PDF")
    reader = PdfReader(io.BytesIO(raw))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(
            f"{url}: {len(reader.pages)} stron, oczekiwano co najwyżej {MAX_PDF_PAGES}"
        )
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def download_text(session: requests.Session, ref: ActRef) -> str:
    """Pobiera PDF obwieszczenia z API ELI i zwraca jego tekst."""
    return download_pdf_text(session, ref.pdf_url)
