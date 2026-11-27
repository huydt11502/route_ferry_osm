# Ferry Route Validity Checker — specification for GitHub Copilot

How to use this file: put it in the repo (e.g. `docs/SPEC.md`) or paste it into Copilot Chat. Ask Copilot to build it step by step: (1) project scaffold + config, (2) input loading, (3) link generation, (4) Google Maps module, (5) news module, (6) social links module, (7) fee extraction, (8) verdict rules, (9) compact result sheet + raw JSON + checkpointing, (10) tests + README. Do not ask it to build everything in one go. Always test with `--limit 5` first.

---

## 1. Context and goal

We maintain a list of ferry routes in Vietnam that are mapped in OpenStreetMap (OSM tag `route=ferry`). Some routes may no longer operate (for example a bridge replaced the ferry), and some fare information may be outdated.

Build a command-line tool that, for each route, collects public evidence from Google Maps, news sites and social media links, and produces a **compact** result sheet so a human can read one row and quickly understand:

- is the ferry still operating? (`valid` / `outdated` / `unknown`)
- is the fare information still fresh or possibly outdated?
- where is the evidence? (one short, clickable link per evidence type)

The result will later be compared with OSM by someone else, so the sheet only needs `osm_id` to join. Keep the sheet short.

Out of scope (do NOT build): redrawing the route geometry, access/vehicle rules, anything that edits OSM.

Language: Vietnamese content (reviews, news). Dates and prices must be parsed from Vietnamese text.

## 2. Input

Option A (preferred for a first run): a CSV file `ferry_check_449.csv`, UTF-8 with BOM, one row per OSM route. Input columns used: `osm_id` (e.g. `way/329804156`), `name` (may be empty, ~46% are empty), `toa_do` ("lat,lng" centroid), `dai_m` (length in metres), `osm_tag_xe_nguoi` (e.g. `motor_vehicle=yes; foot=yes`), `osm_duration`, `osm_operator`, `xa_huyen_tinh` (may be empty). The CSV also contains prefilled search links (`link_google_maps`, `link_google_search_phi`, `link_google_news`, `link_facebook`, `link_instagram`); the tool may reuse them.

Option B: fetch all `route=ferry` in Vietnam from the public Overpass API. For every route keep `osm_id`, `name`, the two end points, the centroid, and the tags `fee`, `charge`, `duration`, `opening_hours`, `motor_vehicle`, `motorcycle`, `foot`.

Unnamed routes: reverse-geocode the centroid with Nominatim (max 1 request/second, send a proper User-Agent) to get ward / district / province, then search by place (for example "bến phà xã X huyện Y"). Cache every geocoding result. Group routes that belong to the same landing (end points within 300 m of each other) so that the same place is not scraped twice.

## 3. What to collect for every route

### 3.1 Google Maps

1. Build the search URL `https://www.google.com/maps/search/?api=1&query=<lat>,<lng>` (or by name). Use `hl=vi`.
2. Among the results, pick the place within 300 m of either end of the route whose category/name looks like a ferry or boat landing (use fuzzy name matching, for example `rapidfuzz`). If several match, keep the nearest and log the others. If none, `unknown`.
3. Extract: place name, place URL, rating, review count, status (operating / temporarily closed / **permanently closed**), opening hours.
4. Reviews: sort by newest. Collect **all reviews of the last 3 months**; if there are none, collect the reviews of the last 12 months. Always record which window was used (`window` = `3m`, `12m` or `none`) and how many reviews fell inside it. Convert relative dates ("2 tháng trước", "a month ago") to ISO dates with `dateparser` (languages `vi`, `en`). Store: review text, rating, ISO date, **and the original relative label**. A date derived from a month-level label is only approximate (about +/- 1 month), so also store `approx=true`. Never present an approximate date as exact. **Do not store reviewer names or profile links.** If the provider returns a per-review URL, store it too.
5. Save the raw JSON/HTML with a timestamp under `evidence/<osm_id>/` so every conclusion can be audited.

Provider options (implement behind one interface, selected in config): `playwright` (browser automation, free, fragile), `places_api` (official Places API New: status, hours, rating, link, but only ~5 reviews), `outscraper` / `serpapi` / `apify` (paid, structured, more stable). Start with `playwright` for the pilot and keep the others as adapters. Never hard-code selectors: keep them in `config.yaml` because Google changes its markup.

### 3.2 News (all outlets, not one by one)

- Primary: Google News RSS search `https://news.google.com/rss/search?q=<query>&hl=vi&gl=VN&ceid=VN:vi`. Filter by `pubDate` yourself; do not rely on the `when:` operator. RSS links are redirects: try to resolve them to the publisher URL, keep the `news.google.com` link if resolving fails. Keep the outlet name from the `<source>` element.
- Secondary: GDELT DOC API (free, no key). Check its supported time span in the documentation before relying on it.
- Queries per route: `"<name>" phà giá vé`, `"<name>" ngừng hoạt động`, `"<name>" cầu thay phà`, `"<name>" bến phà`.
- Keep articles of the last 24 months. In the raw JSON store outlet, title, URL, ISO date, snippet.
- For the **result sheet keep only keywords**, not the title. Keyword list (config): `giá vé`, `tăng giá`, `ngừng hoạt động`, `dừng hoạt động`, `có cầu`, `cầu thay phà`, `hoạt động trở lại`, `sửa chữa`. Show the keywords that actually occur in the article.

### 3.3 Facebook and Instagram (links only)

- Do **not** log in and do **not** scrape post content.
- Only store links that normal web search returns: Google query `site:facebook.com "<name>"` and `site:instagram.com "<name>"`. Keep the most recent public post link per platform with its date if it is visible. Low volume only: this part is optional and may be left to manual checking.

### 3.4 Fare

Collect from: OSM tags (`fee`, `charge`), review texts, news snippets. Extract with regular expressions: `5k`, `5.000đ`, `5000 đồng`, `20 nghìn`, `20 ngàn`, `vnd`, plus the vehicle type (xe máy / xe gắn máy, người đi bộ, ô tô / xe hơi, xe tải, xe đạp). Raw output: a list of `{amount_vnd, vehicle, source_url, source_date}`. For the sheet keep **one** fare line from the **newest source**: `Xe máy 8k · Ô tô 40k` (`k` = thousand VND), its **one** source link and its date. If the newest fare source is older than 12 months, mark the date as possibly outdated.

## 4. Verdict rules (rule-based, no LLM)

- `outdated`: Google status is permanently closed, **or** content inside the window contains a closure phrase and there is no newer evidence of operation. Closure phrases (Vietnamese): `ngừng hoạt động`, `đã ngừng`, `dừng hoạt động`, `không còn hoạt động`, `đã có cầu`, `cầu thay phà`, `không còn phà`, `đóng bến`, `xóa bỏ bến`.
- `valid`: at least one review or news item in the window shows the ferry is running, for example `đi phà`, `qua phà`, `phà chạy`, `chờ phà`, `xếp hàng`, `vừa đi`, or Google status is operating with recent reviews.
- `unknown`: everything else.
- Confidence: `high` = 3 or more recent reviews mention using the ferry, or Google status is operating with recent reviews and a reasonable review count; `medium` = 1 or 2 pieces of evidence; `low` = otherwise.
- Conflicting evidence (for example Google says open, a news article says closed): verdict `unknown`, confidence `low`, and describe the conflict in the reason.
- The reason is one short sentence (at most about 100 characters) that a human can read at a glance.
- A route whose verdict is `unknown`, whose confidence is `low`, or whose evidence conflicts is shown as **"Chưa rõ · cần kiểm tra tay"** (needs manual check).

## 5. Output: compact result sheet (16 columns) + raw data

Deliverables of a run: `ferry_check_result.xlsx` (the 16-column sheet below, real hyperlinks), `results_raw.jsonl` (full structured data), `evidence/<osm_id>/*` (raw pages/JSON) and `run.log`. Use `openpyxl` for the xlsx; wrap text, freeze the header row, colour the verdict cell (green = running, red = stopped, yellow = unknown).

| # | Column | What is displayed |
|---|---|---|
| 1 | `osm_id` | `way/329804156`, hyperlinked to the OSM page |
| 2 | `ten` | route name, or `(không tên)` |
| 3 | `khu_vuc` | ward / district / province |
| 4 | `ket_luan` | **Còn hoạt động / Đã ngừng / Chưa rõ** + confidence (Cao / Trung bình / Thấp); append `" · cần kiểm tra tay"` when manual check is needed |
| 5 | `ly_do` | one short sentence |
| 6 | `google` | `status · rating★ (review count) · N BL / window`, e.g. `Đang hoạt động · 4,1★ (4.628) · 12 BL / 3 tháng` |
| 7 | `binh_luan` | up to 3 newest reviews, one per line: `≈dd/mm/yy ★n quote (max 60 chars…)`. `≈` marks an approximate date |
| 8 | `link_BL` | ONE link: the place page with reviews sorted by newest. Display text `Xem BL` |
| 9 | `bao_chi` | keywords only: `dd/mm/yy · outlet · keyword1, keyword2` (newest relevant article; add a second line only if it contradicts the first) |
| 10 | `link_bao` | ONE link to the most relevant article. Display text `Xem báo` |
| 11 | `facebook` | hyperlink with display text `FB · dd/mm/yy` (post date), or `–` |
| 12 | `instagram` | hyperlink with display text `IG · dd/mm/yy`, or `–` |
| 13 | `gia_ve` | `Xe máy 8k · Ô tô 40k`, or `–` |
| 14 | `nguon_gia` | ONE link to the fare source. Display text `Nguồn` |
| 15 | `ngay_gia` | source date + `mới` (under 12 months) or `có thể cũ` (older), red when possibly outdated |
| 16 | `ghi_chu` | short action note, e.g. "điền xã/huyện/tỉnh rồi tìm lại", "giá từ nguồn 2024, kiểm tra lại" |

Display rules: dates `dd/mm/yy`; `–` for anything not found; never show long raw URLs in cells (use short display text with the hyperlink); the full URLs live in `results_raw.jsonl`.

**If no evidence link was found, fill the link cell with the prefilled search link** so a human can still click and check: `link_BL` ← Google Maps search link, `link_bao` ← Google News search link, `facebook` / `instagram` ← the prefilled Google `site:` search link (display text then `Tìm FB` / `Tìm IG`). Real evidence links always replace search links.

### Raw record per route (`results_raw.jsonl`, one JSON object per line)

```json
{
  "osm_id": "way/329804156",
  "verdict": {"label": "valid", "confidence": "high", "reason": "12 BL/3 tháng nhắc đi phà", "manual": false},
  "google": {"status": "operating", "rating": 4.1, "count": 4628, "window": "3m", "in_window": 12,
             "place_url": "https://www.google.com/maps/...",
             "comments": [{"date": "2026-11-09", "approx": true, "label": "2 tuần trước", "stars": 5, "text": "Phà chạy đều, chờ ~10 phút"}]},
  "news":   [{"date": "2026-08-14", "outlet": "Báo A", "keywords": ["giá vé"], "url": "https://...", "title": "..."}],
  "social": {"fb": [{"date": "2026-11-05", "url": "https://..."}], "ig": []},
  "fee":    {"text": "Xe máy 8k · Ô tô 40k", "url": "https://...", "date": "2026-08-14", "stale": false},
  "collected_at": "2026-12-01T10:00:00+07:00"
}
```

### Link generation for prefilled search links (pure string building, no network access)

- `link_osm` = `https://www.openstreetmap.org/<osm_id>`
- Google Maps = `https://www.google.com/maps/search/?api=1&query=<lat>,<lng>`
- Fare search = `https://www.google.com/search?q=` + url-encode(`<q> giá vé`)
- Google News = `https://news.google.com/search?q=` + url-encode(`<q>`) + `&hl=vi&gl=VN&ceid=VN:vi`
- Facebook = `https://www.google.com/search?q=` + url-encode(`site:facebook.com "<q>"`); Instagram the same with `site:instagram.com`.
- `<q>` is the route name; if it does not start with `phà`, `đò`, `bến`, `tuyến`, `cầu tàu`, `du thuyền` or `ga tàu`, prefix it with `phà `.
- Unnamed routes: only the Google Maps link can be built until `khu_vuc` is filled; then build the search links from the place name.

## 6. Reliability requirements

- Pilot mode `--limit N` (default 5). Resume support: checkpoint after every route in SQLite; a re-run skips finished routes.
- Cache all HTTP responses; keep the run idempotent.
- Be polite: random delay 3–8 seconds between requests, exponential backoff with `tenacity`, at most 3 retries. On captcha or "unusual traffic": stop, write a clear log line, never try to bypass it.
- No secrets in code; API keys only from environment variables; `requirements.txt`; a `README.md` with the exact commands.
- Selectors, queries, phrase lists, keyword lists and time windows live in `config.yaml`.
- Respect the terms of service of each site. Use it only on public pages and at low volume. Do not log in to any account.

## 7. Tests (use fixtures, no network)

- Unit tests: relative-date parsing (Vietnamese and English), fare regexes (`5k`, `5.000đ`, `20 nghìn`), verdict rules (valid / outdated / conflict / unknown), cell formatting (comment line, news keyword line, fare line, `mới` / `có thể cũ`), link generation, and 300 m place matching.
- Provide 3–4 saved sample inputs (fake review lists and news items) so the tests run offline.

## 8. Pilot routes (public OSM data)

| Route | OSM | Ends (lat,lng) | Note |
|---|---|---|---|
| Phà Bình Khánh | `way/329804156` | 10.67449,106.76767 → 10.66624,106.77516 | vehicles and people, 1364 m |
| Phà Cát Lái | `way/583820290` | 10.75708,106.78861 → 10.75213,106.78993 | 566 m |
| Phà An Sơn | `way/531200807` | 10.92057,106.66620 → 10.92225,106.66651 | 188 m |
| Đò Bình Quới | `way/623048783` | 10.83357,106.74414 → 10.83550,106.74561 | 268 m |
| Phà Phú Định | `way/489086382` | 10.70857,106.61900 → 10.71061,106.61902 | 225 m |
| Đò Phước Khánh | `way/693320474` | 10.67482,106.76646 → 10.67434,106.78927 | motorcycles only, 2760 m |

These are real, well-known ferries that are expected to be operating. If the tool returns `Đã ngừng` or `Chưa rõ` for most of them, suspect a bug in the tool first (selectors, matching, date parsing), not the ferries.

## 9. Definition of done

1. `python -m ferrycheck --input ferry_check_449.csv --limit 6` finishes without error.
2. `ferry_check_result.xlsx` has the 16 columns, a conclusion for each processed route, and for every route that is not `Chưa rõ` at least one clickable evidence link with a date (review date, article date or post date).
3. `results_raw.jsonl` contains the full URLs and raw evidence for each route.
4. Re-running does not scrape the same route again.
5. Tests pass offline. The README explains setup, the pilot run, and the full run.
