from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Protocol
from urllib.parse import parse_qs, quote_plus, urlparse

from .dates import parse_date, parse_date_detail
from .fare import parse_fares
from .models import Evidence, NewsItem, Review, Route
from .api_providers import GoogleInternalReviewsProvider, GooglePlacesApiProvider, OutscraperProvider, SerpApiProvider

LOGGER = logging.getLogger(__name__)
NEWS_KEYWORDS = (
    "giá vé", "tăng giá", "ngừng hoạt động", "dừng hoạt động", "có cầu",
    "cầu thay phà", "hoạt động trở lại", "sửa chữa",
)


class EvidenceProvider(Protocol):
    def collect(self, route: Route) -> Evidence: ...


class OfflineProvider:
    def collect(self, route: Route) -> Evidence:
        return Evidence()


class GoogleNewsProvider:
    def __init__(self, timeout: int = 20, cache_dir: str = "cache/http"):
        self.timeout = timeout
        self.cache_dir = cache_dir

    def _get(self, url: str) -> bytes:
        import hashlib
        from pathlib import Path
        target = Path(self.cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".body")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return target.read_bytes()
        request = urllib.request.Request(url, headers={"User-Agent": "ferrycheck/0.1 (public research)"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read()
        target.write_bytes(body)
        return body

    def collect(self, route: Route) -> Evidence:
        if not route.query:
            return Evidence()
        query = quote_plus(f'"{route.query}"')
        url = f"https://news.google.com/rss/search?q={query}&hl=vi&gl=VN&ceid=VN:vi"
        cutoff = date.today() - timedelta(days=730)
        news: list[NewsItem] = []
        raw = self._get(url)
        root = ET.fromstring(raw)
        for item in root.findall(".//item"):
            published = parse_date(item.findtext("pubDate", ""), relative_base=date.today())
            if published and published < cutoff:
                continue
            source = item.find("source")
            outlet = (source.text or "").strip() if source is not None else ""
            title = html.unescape(item.findtext("title", "").strip())
            link = item.findtext("link", "").strip()
            description = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description", "").strip()))
            description = re.sub(r"\s+", " ", description).strip()
            haystack = f"{title} {description}".lower()
            keywords = [keyword for keyword in NEWS_KEYWORDS if keyword in haystack]
            news.append(NewsItem(outlet=outlet, title=title, url=link, date=published, snippet=description[:500], keywords=keywords))
        return Evidence(news=news, raw={"provider": "google_news_rss", "url": url})


class SocialSearchProvider:
    """Collect only public result links/snippets; never logs in or opens a post."""

    def __init__(self, timeout: int = 20, cache_dir: str = "cache/http"):
        self.timeout = timeout
        self.cache_dir = cache_dir

    def _search(self, query: str) -> list[dict[str, str]]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(locale="vi-VN")
                try:
                    page.goto("https://www.google.com/search?q=" + quote_plus(query) + "&hl=vi", wait_until="domcontentloaded", timeout=self.timeout * 1000)
                    page.wait_for_timeout(1500)
                    anchors = page.locator("a").evaluate_all("els => els.map(a => ({url: a.href, text: a.innerText})).filter(x => x.url)")
                finally:
                    browser.close()
            results = []
            for item in anchors:
                link = item["url"]
                if link.startswith("http") and any(domain in link for domain in ("facebook.com/", "instagram.com/")) and "/search" not in link:
                    results.append({"url": link, "snippet": item.get("text", "")[:300]})
            if results:
                unique = {item["url"].split("?")[0]: item for item in results}
                return list(unique.values())[:5]
        except Exception as exc:
            LOGGER.warning("browser social search failed: %s", exc)
        # Google may return a consent/captcha page. A secondary public search
        # is still limited to direct Facebook/Instagram URLs and never opens posts.
        try:
            import hashlib
            from pathlib import Path
            bing_url = "https://www.bing.com/search?q=" + quote_plus(query)
            target = Path(self.cache_dir) / (hashlib.sha256(bing_url.encode()).hexdigest() + ".html")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                body = target.read_text(encoding="utf-8", errors="replace")
            else:
                request = urllib.request.Request(bing_url, headers={"User-Agent": "ferrycheck/0.1 (public research)"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
                target.write_text(body, encoding="utf-8")
            found = []
            for href, title in re.findall(r'<li class="b_algo".*?<a href="([^"]+)"[^>]*>(.*?)</a>', body, re.I | re.S):
                link = html.unescape(href)
                if link.startswith("http") and any(domain in link for domain in ("facebook.com/", "instagram.com/")) and "/search" not in link:
                    found.append({"url": link, "snippet": re.sub("<[^>]+>", " ", title)[:300]})
            if found:
                return list({item["url"].split("?")[0]: item for item in found}.values())[:5]
        except Exception as exc:
            LOGGER.warning("secondary social search failed: %s", exc)
        import hashlib
        from pathlib import Path
        url = "https://www.google.com/search?q=" + quote_plus(query) + "&hl=vi"
        target = Path(self.cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            body = target.read_text(encoding="utf-8", errors="replace")
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "ferrycheck/0.1 (public research)"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            target.write_text(body, encoding="utf-8")
        results = []
        for href, snippet in re.findall(r'<a href="([^" ]+)"[^>]*>(.*?)</a>', body, re.I | re.S):
            if href.startswith("/url?"):
                link = parse_qs(urlparse(href).query).get("q", [""])[0]
            else:
                link = href
            if link.startswith("http") and any(domain in link for domain in ("facebook.com/", "instagram.com/")) and "/search" not in link:
                results.append({"url": html.unescape(link.split("&amp;")[0]), "snippet": re.sub("<[^>]+>", " ", snippet)[:300]})
        return results[:5]

    def collect(self, route: Route) -> Evidence:
        if not route.query:
            return Evidence()
        facebook = self._search(f'site:facebook.com "{route.query}"')
        instagram = self._search(f'site:instagram.com "{route.query}"')
        return Evidence(facebook_links=facebook, instagram_links=instagram, raw={"provider": "google_search_social"})


class GoogleMapsProvider:
    """Best-effort public Google Maps collector using Playwright."""

    def __init__(self, headless: bool = True, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    def collect(self, route: Route) -> Evidence:
        if not route.toa_do:
            return Evidence(raw={"provider": "google_maps", "error": "route has no coordinates"})
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Google Maps collection requires playwright and a Chromium browser") from exc
        search_query = route.name or route.toa_do
        url = "https://www.google.com/maps/search/?api=1&query=" + quote_plus(search_query) + "&hl=vi"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page(locale="vi-VN")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(2500)
                body = page.locator("body").inner_text(timeout=self.timeout_ms)
                place_links = page.locator('a[href*="/maps/place/"]').evaluate_all("els => els.map(a => a.href)")
                place_url = place_links[0] if place_links else ""
                if not place_url:
                    more = page.get_by_role("button", name=re.compile(r"Xem thêm|See more", re.I))
                    if more.count():
                        try:
                            more.first.click(timeout=3000)
                            page.wait_for_timeout(1200)
                            if "/maps/place/" in page.url:
                                place_url = page.url
                                body = page.locator("body").inner_text(timeout=self.timeout_ms)
                        except Exception:
                            pass
                place_name = route.name if route.name and route.name.lower() in body.lower() else ""
                status = "permanently closed" if re.search(r"đã đóng cửa vĩnh viễn|permanently closed", body, re.I) else ""
                if not status and re.search(r"đang mở|open", body, re.I):
                    status = "operating"
                rating_match = re.search(r"([0-5],[0-9])\s*\(([^)]+)\)", body)
                reviews = []
                cards = page.locator("[data-review-id]").evaluate_all("els => els.map(e => { const b=e.querySelector('button.aL6Kxe'); return {id:e.dataset.reviewId, url:e.dataset.href || '', text:(b ? b.innerText : e.innerText), full:e.innerText, aria:(b ? b.getAttribute('aria-label') : '')}; })")
                for card in cards:
                    label_match = re.search(r"(\d+\s+(?:tháng|tuần|ngày|năm)\s+trước|hôm qua|a month ago|\d+ months? ago|\d+ weeks? ago|\d+ days? ago)", card.get("full", ""), re.I)
                    label = label_match.group(1) if label_match else ""
                    review_date, approx = parse_date_detail(label, relative_base=date.today()) if label else (None, False)
                    star_match = re.search(r"([1-5])\s*(?:sao|stars?)", card.get("aria", "") + " " + card.get("full", ""), re.I)
                    reviews.append(Review(text=card.get("text", "")[:1000], date=review_date, rating=star_match.group(1) if star_match else "", label=label, approx=approx, url=card.get("url", "")))
                cutoff = date.today() - timedelta(days=90)
                recent = [review for review in reviews if review.date and review.date >= cutoff]
                window = "3m"
                if not recent:
                    cutoff = date.today() - timedelta(days=365)
                    recent = [review for review in reviews if review.date and review.date >= cutoff]
                    window = "12m" if recent else "none"
                recent.sort(key=lambda review: review.date or date.min, reverse=True)
                return Evidence(place_name=place_name, place_url=place_url, google_status=status, rating=rating_match.group(1) if rating_match else "",
                                review_count=rating_match.group(2) if rating_match else "",
                                reviews=recent, review_window=window,
                                raw={"provider": "google_maps", "url": url, "text": body[:100_000], "html": page.content()[:500_000]})
            finally:
                browser.close()


class ScrapeProvider:
    def __init__(self, cache_dir: str = "cache/http", maps: bool = False, maps_provider: str = "playwright"):
        self.news = GoogleNewsProvider(cache_dir=cache_dir)
        self.social = SocialSearchProvider(cache_dir=cache_dir)
        self.maps = None
        if maps:
            self.maps = {"playwright": GoogleMapsProvider(), "places_api": GooglePlacesApiProvider(),
                         "serpapi": SerpApiProvider(), "outscraper": OutscraperProvider(),
                         "google_internal": GoogleInternalReviewsProvider()}[maps_provider]

    def collect(self, route: Route) -> Evidence:
        evidence = self.news.collect(route)
        if self.maps:
            maps_evidence = self.maps.collect(route)
            evidence.place_name = maps_evidence.place_name
            evidence.place_url = maps_evidence.place_url
            evidence.google_status = maps_evidence.google_status
            evidence.rating = maps_evidence.rating
            evidence.review_count = maps_evidence.review_count
            evidence.hours = maps_evidence.hours
            evidence.reviews = maps_evidence.reviews
            evidence.review_window = maps_evidence.review_window
            evidence.raw["google_maps"] = maps_evidence.raw
        social = self.social.collect(route)
        evidence.facebook_links = social.facebook_links
        evidence.instagram_links = social.instagram_links
        evidence.raw.update(social.raw)
        for item in evidence.news:
            text = f"{item.title} {item.snippet}"
            evidence.fares.extend(parse_fares(text, source_url=item.url, source_date=item.date.isoformat() if item.date else "", require_vehicle=True))
        return evidence


class RateLimitedProvider:
    def __init__(self, provider: EvidenceProvider, min_delay: float = 3.0):
        self.provider = provider
        self.min_delay = min_delay
        self._last_request = 0.0

    def collect(self, route: Route) -> Evidence:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        try:
            return self.provider.collect(route)
        finally:
            self._last_request = time.monotonic()
