from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import re
from datetime import date, timedelta
from typing import Any

from .dates import parse_date, parse_date_detail
from .models import Evidence, Review, Route


def _request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                 payload: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _window(reviews: list[Review]) -> tuple[list[Review], str]:
    today = date.today()
    recent = [item for item in reviews if item.date and item.date >= today - timedelta(days=90)]
    window = "3m"
    if not recent:
        recent = [item for item in reviews if item.date and item.date >= today - timedelta(days=365)]
        window = "12m" if recent else "none"
    recent.sort(key=lambda item: item.date or date.min, reverse=True)
    return recent, window


def _review(value: dict[str, Any]) -> Review:
    text = value.get("text")
    if isinstance(text, dict):
        text = text.get("text", "")
    text = str(text or value.get("snippet") or value.get("content") or "")
    label = str(value.get("relativePublishTimeDescription") or value.get("date") or value.get("date_published") or "")
    iso = value.get("publishTime") or value.get("iso_date")
    review_date = parse_date(str(iso), relative_base=date.today()) if iso else parse_date(label, relative_base=date.today())
    _, approx = parse_date_detail(label, relative_base=date.today()) if label else (review_date, False)
    rating = value.get("rating") or value.get("stars") or ""
    return Review(text=text[:2000], date=review_date, rating=str(rating), label=label, approx=approx,
                  url=str(value.get("url") or value.get("link") or ""))


class _KeyedProvider:
    env_name = ""
    provider_name = "api"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.api_key = os.environ.get(self.env_name, "").strip()

    def missing(self, route: Route) -> Evidence:
        return Evidence(raw={"provider": self.provider_name, "status": "missing_api_key", "env": self.env_name})


class GooglePlacesApiProvider(_KeyedProvider):
    """Google Places API (New), using Text Search then Place Details."""

    env_name = "GOOGLE_MAPS_API_KEY"
    provider_name = "google_places_api"

    def collect(self, route: Route) -> Evidence:
        if not self.api_key:
            return self.missing(route)
        query = route.query or route.name or route.toa_do
        headers = {"Content-Type": "application/json", "X-Goog-Api-Key": self.api_key,
                   "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.rating,places.userRatingCount,places.businessStatus,places.regularOpeningHours"}
        search = _request_json("https://places.googleapis.com/v1/places:searchText", method="POST",
                               headers=headers, payload={"textQuery": query, "languageCode": "vi"}, timeout=self.timeout)
        places = search.get("places", []) if isinstance(search, dict) else []
        if not places:
            return Evidence(raw={"provider": self.provider_name, "status": "no_place_match", "query": query})
        place = places[0]
        place_id = str(place.get("id", ""))
        detail = place
        if place_id:
            detail_headers = {"X-Goog-Api-Key": self.api_key,
                              "X-Goog-FieldMask": "id,displayName,googleMapsUri,rating,userRatingCount,businessStatus,regularOpeningHours,reviews"}
            detail = _request_json("https://places.googleapis.com/v1/places/" + urllib.parse.quote(place_id, safe=""),
                                   headers=detail_headers, timeout=self.timeout)
        reviews = [_review(item) for item in detail.get("reviews", []) if isinstance(item, dict)]
        reviews, window = _window(reviews)
        hours = detail.get("regularOpeningHours", {}).get("weekdayDescriptions", [])
        return Evidence(place_name=detail.get("displayName", {}).get("text", route.name),
                        place_url=detail.get("googleMapsUri", ""),
                        google_status=str(detail.get("businessStatus", "")),
                        hours="; ".join(hours), rating=str(detail.get("rating", "")),
                        review_count=str(detail.get("userRatingCount", "")), reviews=reviews,
                        review_window=window,
                        raw={"provider": self.provider_name, "status": "ok", "place_id": place_id,
                             "search": search, "detail": detail})


class SerpApiProvider(_KeyedProvider):
    env_name = "SERPAPI_KEY"
    provider_name = "serpapi_google_maps"

    def collect(self, route: Route) -> Evidence:
        if not self.api_key:
            return self.missing(route)
        params = urllib.parse.urlencode({"engine": "google_maps", "q": route.query or route.name or route.toa_do,
                                         "hl": "vi", "api_key": self.api_key})
        data = _request_json("https://serpapi.com/search.json?" + params, timeout=self.timeout)
        place = data.get("place_results") or (data.get("local_results") or [{}])[0]
        place = place if isinstance(place, dict) else {}
        source_reviews = place.get("reviews") or data.get("reviews") or []
        reviews = [_review(item) for item in source_reviews if isinstance(item, dict)]
        reviews, window = _window(reviews)
        return Evidence(place_name=str(place.get("title") or place.get("name") or route.name),
                        place_url=str(place.get("link") or place.get("maps_link") or ""),
                        google_status=str(place.get("business_status") or place.get("hours") or ""),
                        hours=str(place.get("hours") or ""), rating=str(place.get("rating") or ""),
                        review_count=str(place.get("reviews") if isinstance(place.get("reviews"), (int, str)) else place.get("reviews_count") or ""),
                        reviews=reviews, review_window=window,
                        raw={"provider": self.provider_name, "status": "ok", "response": data})


class OutscraperProvider(_KeyedProvider):
    env_name = "OUTSCRAPER_API_KEY"
    provider_name = "outscraper_google_maps_reviews"

    def collect(self, route: Route) -> Evidence:
        if not self.api_key:
            return self.missing(route)
        query = route.query or route.name or route.toa_do
        params = urllib.parse.urlencode({"query": query, "limit": "20", "async": "false"})
        request_url = "https://api.outscraper.com/google-maps-reviews?" + params
        data = _request_json(request_url, headers={"X-API-KEY": self.api_key}, timeout=self.timeout)
        records = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        place = records[0] if records and isinstance(records[0], dict) else {}
        source_reviews = place.get("reviews_data") or place.get("reviews") or []
        reviews = [_review(item) for item in source_reviews if isinstance(item, dict)]
        reviews, window = _window(reviews)
        return Evidence(place_name=str(place.get("name") or route.name),
                        place_url=str(place.get("google_maps_url") or place.get("link") or ""),
                        google_status=str(place.get("business_status") or ""),
                        hours=str(place.get("working_hours") or ""), rating=str(place.get("rating") or ""),
                        review_count=str(place.get("reviews_count") or place.get("reviews") if not isinstance(place.get("reviews"), list) else ""),
                        reviews=reviews, review_window=window,
                        raw={"provider": self.provider_name, "status": "ok", "response": data})


class GoogleInternalReviewsProvider:
    """Low-volume best-effort reader for Google's public Maps review feed.

    This is an undocumented web endpoint used by Maps itself. It is deliberately
    limited to one search and one review page per route; it is not a bypass for
    authentication or rate limits.
    """

    provider_name = "google_internal_reviews"
    _search_pb = ("!1s{query}!7i20!8i0!10b1!12m6!1m1!18b1!2m1!20e3!6m1!114b1"
                  "!17m1!3e1!20m57!2m2!1i203!2i100!3m2!2i4!5b1"
                  "!6m6!1m2!1i86!2i86!1m2!1i408!2i240!7m33!1m3!1e1!2b0!3e3"
                  "!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3!1m3!1e8!2b0!3e3"
                  "!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2!1m3!1e10!2b0!3e4"
                  "!1m3!1e9!2b1!3e2!2b1!9b0!15m8!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20")

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def _get(self, url: str) -> str:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "vi,en;q=0.8", "Cookie": "SOCS=CAISHAgBEhJnd3NfMjAyMzAyMjgtMF9SQzEaAmVuIAEaBgiA_LyaBg; CONSENT=YES+cb",
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _post_reviews(self, ftid: str, source_path: str) -> str:
        inner = json.dumps([[[ftid], None, None, None, None, [None, None, None, [[1], [3]]]],
                            [3, ""], None, None, [None, None, None, None, None, None, 81], None, None,
                            [None, 1, 1, None, 1, None, 1, None, None, None, None, [1, 1, None, [[1]]]],
                            None, None, [3, 1, None, None, None, [2]], None, [1]], separators=(",", ":"))
        freq = json.dumps([[['qv9Egd', inner, None, "generic"]]], separators=(",", ":"))
        query = urllib.parse.urlencode({"rpcids": "qv9Egd", "source-path": source_path,
                                        "hl": "vi", "_reqid": "100000", "rt": "c"})
        body = urllib.parse.urlencode({"f.req": freq})
        request = urllib.request.Request("https://www.google.com/maps/_/MapsWizUi/data/batchexecute?" + query,
                                         data=body.encode(), method="POST", headers={
                                             "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                                             "Accept-Language": "vi,en;q=0.8",
                                         })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    @staticmethod
    def _parse_reviews(body: str) -> list[Review]:
        reviews: list[Review] = []
        # Review entries are nested JSON frames. Search only long strings near
        # a relative date and a 1-5 rating, avoiding UI labels.
        for line in body.splitlines():
            if "wrb.fr" not in line:
                continue
            strings = re.findall(r'"((?:\\.|[^"\\]){2,})"', line)
            strings = [bytes(value, "utf-8").decode("unicode_escape", errors="ignore") for value in strings]
            labels = [value for value in strings if re.search(r"(?:ago|trước)$", value, re.I)]
            texts = [value for value in strings if len(value) >= 35 and "http" not in value]
            if not labels or not texts:
                continue
            label = labels[0]
            review_date, approx = parse_date_detail(label, relative_base=date.today())
            rating = next((value for value in strings if re.fullmatch(r"[1-5](?:\.0)?", value)), "")
            reviews.append(Review(text=max(texts, key=len)[:2000], date=review_date, rating=rating,
                                  label=label, approx=approx))
        unique = {(item.text, item.label): item for item in reviews}
        return list(unique.values())[:3]

    def collect(self, route: Route) -> Evidence:
        query = route.query or route.name or route.toa_do
        search_url = "https://www.google.com/search?tbm=map&hl=vi&gl=vn&q=" + urllib.parse.quote_plus(query)
        search_url += "&pb=" + urllib.parse.quote(self._search_pb.format(query=urllib.parse.quote_plus(query)), safe="")
        try:
            search_body = self._get(search_url)
            match = re.search(r'"(0x[0-9a-f]{12,}:0x[0-9a-f]{10,})","([^"]{2,120})",null,\[', search_body, re.I)
            if not match:
                return Evidence(raw={"provider": self.provider_name, "status": "no_place_match", "search_url": search_url})
            ftid, place_name = match.groups()
            source_path = "/maps/place/" + urllib.parse.quote(place_name.replace(" ", "+"))
            body = self._post_reviews(ftid, source_path)
            reviews = self._parse_reviews(body)
            reviews, window = _window(reviews)
            return Evidence(place_name=place_name, reviews=reviews, review_window=window,
                            raw={"provider": self.provider_name, "status": "ok" if reviews else "review_text_gated",
                                 "ftid": ftid, "search_url": search_url, "response_excerpt": body[:20000]})
        except Exception as exc:
            return Evidence(raw={"provider": self.provider_name, "status": "request_failed", "error": str(exc)})

