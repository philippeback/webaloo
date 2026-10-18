from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .storage import generate_monogram, slugify

logger = logging.getLogger("webaloo.icons")

ALLOWED_ICON_EXTENSIONS = {".png", ".svg", ".ico", ".webp", ".jpg", ".jpeg", ".gif"}

CONTENT_TYPE_EXT_MAP = {
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
}


def sanitize_icon_filename(filename: str, prefix: str = "custom") -> str:
    """REQ-ICON-005: Sanitize uploaded icon filename and preserve allowed image extension."""
    path = Path(filename or "icon.png")
    ext = path.suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in ALLOWED_ICON_EXTENSIONS:
        ext = ".png"
    stem = slugify(path.stem, fallback=prefix)
    return f"{stem}{ext}"


def _parse_icon_size(sizes_attr: str | None) -> int:
    if not sizes_attr:
        return 0
    sizes_str = str(sizes_attr).strip().lower()
    if sizes_str == "any":
        return 512
    best = 0
    for part in sizes_str.split():
        m = re.match(r"^(\d+)x(\d+)$", part)
        if m:
            best = max(best, int(m.group(1)))
    return best


def _extract_html_metadata(html_text: str, base_url: str) -> tuple[str | None, list[tuple[int, str]]]:
    """Parse HTML to extract <title> and candidate icon URLs scored by priority/size."""
    title: str | None = None
    candidates: list[tuple[int, str]] = []

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if not title:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            if og_title and og_title.get("content"):
                title = str(og_title["content"]).strip()

        for link in soup.find_all("link"):
            rel_raw = link.get("rel")
            if not rel_raw:
                continue
            rel = " ".join(rel_raw).lower() if isinstance(rel_raw, list) else str(rel_raw).lower()
            href = link.get("href")
            if not href or not str(href).strip():
                continue
            full_href = urljoin(base_url, str(href).strip())
            size_score = _parse_icon_size(link.get("sizes"))

            if "apple-touch-icon" in rel:
                priority = 300 + (size_score or 180)
                candidates.append((priority, full_href))
            elif "icon" in rel:
                priority = 100 + (size_score or 32)
                candidates.append((priority, full_href))
    except ImportError:
        # Regex fallback if bs4 is unavailable
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        if m_title:
            title = re.sub(r"\s+", " ", m_title.group(1)).strip()

    candidates.sort(key=lambda item: item[0], reverse=True)
    return title, candidates


def _guess_extension(url: str, content_type: str | None, content: bytes) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in CONTENT_TYPE_EXT_MAP:
            return CONTENT_TYPE_EXT_MAP[ct]
    parsed_path = urlparse(url).path.lower()
    for ext in ALLOWED_ICON_EXTENSIONS:
        if parsed_path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content.startswith(b"<svg") or b"<svg" in content[:256]:
        return ".svg"
    if content.startswith(b"\x00\x00\x01\x00"):
        return ".ico"
    return ".png"


async def fetch_site_icon_and_metadata(
    url: str,
    icons_dir: Path,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """
    REQ-ICON-002 & REQ-ICON-003:
    Inspect target URL, extract title and best icon, save into icons_dir,
    or gracefully fall back to a monogram badge on failure/timeout.
    """
    raw_url = (url or "").strip()
    parsed = urlparse(raw_url)
    domain = (parsed.hostname or "").replace("www.", "")
    domain_stem = slugify(domain.split(".")[0] if domain else "site", fallback="site")
    fallback_title = (domain.split(".")[0].capitalize() if domain else "Bookmark")
    fallback_monogram = generate_monogram(fallback_title, raw_url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "ok": False,
            "title": fallback_title,
            "icon_type": "monogram",
            "icon_url": None,
            "monogram": fallback_monogram,
            "fallback": True,
        }

    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/apng,*/*;q=0.8",
    }

    discovered_title: str | None = None
    icon_candidates: list[str] = []

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            verify=False,
            headers=headers,
        ) as client:
            try:
                resp = await client.get(raw_url)
                if resp.status_code < 400 and "text/html" in resp.headers.get("content-type", "").lower():
                    title, scored = _extract_html_metadata(resp.text, str(resp.url))
                    if title:
                        discovered_title = title
                    icon_candidates.extend(href for _, href in scored)
            except Exception as page_exc:
                logger.debug("Page fetch failed for %s: %s", raw_url, page_exc)

            # Standard fallback paths on origin
            for default_path in ("/apple-touch-icon.png", "/favicon.ico"):
                candidate = urljoin(origin, default_path)
                if candidate not in icon_candidates:
                    icon_candidates.append(candidate)

            for icon_href in icon_candidates:
                try:
                    icon_resp = await client.get(icon_href)
                    if icon_resp.status_code == 200 and len(icon_resp.content) >= 32:
                        ct = icon_resp.headers.get("content-type", "").lower()
                        if "text/html" in ct and b"<svg" not in icon_resp.content[:512]:
                            continue
                        ext = _guess_extension(icon_href, ct, icon_resp.content)
                        icons_dir.mkdir(parents=True, exist_ok=True)
                        filename = f"{domain_stem}{ext}"
                        target_path = icons_dir / filename
                        target_path.write_bytes(icon_resp.content)
                        final_title = discovered_title or fallback_title
                        return {
                            "ok": True,
                            "title": final_title,
                            "icon_type": "cached",
                            "icon_url": f"/icons/{filename}",
                            "monogram": generate_monogram(final_title, raw_url),
                            "fallback": False,
                        }
                except Exception as icon_exc:
                    logger.debug("Candidate icon download failed (%s): %s", icon_href, icon_exc)
                    continue
    except Exception as exc:
        logger.debug("Icon discovery client error for %s: %s", raw_url, exc)

    final_title = discovered_title or fallback_title
    return {
        "ok": False,
        "title": final_title,
        "icon_type": "monogram",
        "icon_url": None,
        "monogram": generate_monogram(final_title, raw_url),
        "fallback": True,
    }
