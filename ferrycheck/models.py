from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Route:
    osm_id: str
    name: str = ""
    toa_do: str = ""
    dai_m: str = ""
    osm_tag_xe_nguoi: str = ""
    osm_duration: str = ""
    osm_operator: str = ""
    xa_huyen_tinh: str = ""
    fee: str = ""
    charge: str = ""
    opening_hours: str = ""
    endpoints: list[tuple[float, float]] = field(default_factory=list)

    @property
    def query(self) -> str:
        value = (self.name or self.xa_huyen_tinh).strip()
        prefixes = ("phà", "đò", "bến", "tuyến", "cầu tàu", "du thuyền", "ga tàu")
        return value if value.lower().startswith(prefixes) else f"phà {value}" if value else ""


@dataclass
class Review:
    text: str
    date: date | None = None
    rating: str = ""
    label: str = ""
    approx: bool = False
    url: str = ""


@dataclass
class NewsItem:
    outlet: str
    title: str
    url: str
    date: date | None = None
    snippet: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    place_name: str = ""
    place_url: str = ""
    google_status: str = ""
    hours: str = ""
    rating: str = ""
    review_count: str = ""
    reviews: list[Review] = field(default_factory=list)
    review_window: str = "none"
    news: list[NewsItem] = field(default_factory=list)
    facebook_links: list[dict[str, Any]] = field(default_factory=list)
    instagram_links: list[dict[str, Any]] = field(default_factory=list)
    fares: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
