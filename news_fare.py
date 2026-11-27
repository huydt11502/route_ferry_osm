"""Báo chí + giá vé cho từng tuyến phà.

Với mỗi tên phà:
  1. Lấy Google News RSS (nguồn cấp tin công khai, không captcha).
  2. Lọc bài trong N ngày gần nhất (mặc định 30), chọn 1-2 bài mới nhất (ưu tiên có từ khóa).
  3. Lấy link gốc của báo (xem resolve_link).
  4. Đọc bài, rút từ khóa và các dòng giá vé.
  5. Ghi CSV + JSON.

Chạy (máy cá nhân):
  pip install requests
  python ferry/news_fare.py --name "phà Cát Lái" --name "phà Bình Khánh"
  python ferry/news_fare.py --csv ferry/runs/kiem_tra/ferry_check_449.csv --limit 5
  python ferry/news_fare.py --selftest        # kiểm thử không cần mạng

Chỉ dùng trang công khai, số lượng ít, nghỉ giữa các yêu cầu. Gặp captcha/403 thì dừng, không vượt.
"""
import argparse
import csv
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote

UA = {"User-Agent": "Mozilla/5.0 (ferry-check; low volume, contact: your-email@example.com)"}
KEYWORDS = ["giá vé", "tăng giá", "điều chỉnh giá", "giá mới", "ngừng hoạt động", "dừng hoạt động", "tạm ngừng",
            "tạm dừng", "hoạt động trở lại", "hoạt động lại", "có cầu", "cầu thay phà", "sửa chữa", "đóng bến", "ùn tắc"]
# Trang tìm kiếm của chính báo, dùng để lấy link gốc khi link Google News không theo được.
# Chỉ tuoitre.vn đã kiểm tra. Thêm báo khác khi đã tự kiểm tra định dạng link tìm kiếm.
OUTLET_SEARCH = {"tuoitre.vn": "https://tuoitre.vn/tim-kiem.htm?keywords={q}"}

VEHICLES = [("Đi bộ/xe đạp", r"người đi bộ|đi bộ|xe đạp"), ("Xe máy", r"xe máy|xe gắn máy|mô tô"),
            ("Ô tô <7 chỗ", r"dưới 7 chỗ|xe con|ô tô con"), ("Xe tải", r"xe tải|tải trọng")]
MONEY = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:đ|đồng|vnd|k|nghìn|ngàn)?", re.I)


def query_for(name):
    name = name.strip()
    return name if re.match(r"^(phà|đò|bến|tuyến|cầu tàu)", name, re.I) else f"phà {name}"


def parse_rss(xml_text):
    """-> list[{title, link, date(datetime UTC), outlet, outlet_url}]"""
    out = []
    for it in ET.fromstring(xml_text).iter("item"):
        src = it.find("source")
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:  # noqa: BLE001
            continue
        out.append({"title": unescape(it.findtext("title") or ""), "link": it.findtext("link") or "",
                    "date": dt.astimezone(timezone.utc),
                    "outlet": (src.text if src is not None else ""), "outlet_url": (src.get("url") if src is not None else "")})
    return out


def keywords_in(text):
    low = text.lower()
    return [k for k in KEYWORDS if k in low]


def pick(items, days, now, n=2):
    """Lọc trong `days` ngày, ưu tiên bài có từ khóa, rồi mới nhất."""
    lim = now - timedelta(days=days)
    ok = [i for i in items if i["date"] >= lim]
    for i in ok:
        i["keywords"] = keywords_in(i["title"])
    ok.sort(key=lambda i: (-len(i["keywords"]), -i["date"].timestamp()))
    return ok[:n]


def fare_lines(text):
    """Heuristic: dòng có loại xe + số tiền. LUÔN cần người xem lại; đây không phải kết luận chắc chắn."""
    res = []
    for line in re.split(r"[\n\r]+|(?<=\.)\s", text):
        for label, rx in VEHICLES:
            if re.search(rx, line, re.I):
                amounts = [m.group(1) for m in MONEY.finditer(line) if len(re.sub(r"\D", "", m.group(1))) >= 4]
                if amounts:
                    res.append({"vehicle": label, "amounts": amounts[:4], "line": line.strip()[:200]})
                break
    return res


def effective_date(text):
    m = re.search(r"(?:từ|kể từ|có hiệu lực(?: từ)?)\s*(?:ngày\s*)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", text, re.I)
    return m.group(0) if m else "chưa rõ ngày hiệu lực"


def resolve_link(item, http):
    """Link gốc của báo. Link news.google.com/rss/articles/... chạy bằng JavaScript nên thường không theo được.
    Thử: (1) theo chuyển hướng HTTP; (2) tìm tiêu đề trên trang tìm kiếm của chính báo; (3) giữ link Google News."""
    try:
        r = http.get(item["link"], headers=UA, timeout=20, allow_redirects=True)
        if "news.google.com" not in r.url and "consent.google" not in r.url:
            return r.url
    except Exception:  # noqa: BLE001
        pass
    host = re.sub(r"^https?://(www\.)?", "", item.get("outlet_url") or "").strip("/")
    tpl = OUTLET_SEARCH.get(host)
    if tpl:
        try:
            r = http.get(tpl.format(q=quote(item["title"][:60])), headers=UA, timeout=20)
            for m in re.finditer(r'href="(/[^"]+?\d{10,}\.htm)"', r.text):
                return "https://" + host + m.group(1)
        except Exception:  # noqa: BLE001
            pass
    return item["link"]


def read_article(url, http):
    r = http.get(url, headers=UA, timeout=25)
    if r.status_code in (403, 429) or "captcha" in r.text[:3000].lower():
        raise RuntimeError(f"bị chặn ({r.status_code}) tại {url}: dừng, không vượt")
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
    html = re.sub(r"(?i)</(p|tr|li|div|h\d)>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))


def run_route(name, days, http, now=None):
    now = now or datetime.now(timezone.utc)
    q = query_for(name)
    url = f"https://news.google.com/rss/search?q={quote(chr(34) + q + chr(34))}&hl=vi&gl=VN&ceid=VN:vi"
    items = parse_rss(http.get(url, headers=UA, timeout=25).text)
    res = {"name": name, "query": q, "window_days": days, "total_in_feed": len(items), "articles": []}
    for it in pick(items, days, now):
        link = resolve_link(it, http)
        a = {"date": it["date"].astimezone(timezone(timedelta(hours=7))).strftime("%d/%m/%y"), "outlet": it["outlet"],
             "title": it["title"], "url": link, "keywords": it["keywords"], "fare_lines": [], "effective": ""}
        if "news.google.com" not in link:
            try:
                txt = read_article(link, http)
                a["keywords"] = sorted(set(a["keywords"] + keywords_in(txt)))
                a["fare_lines"] = fare_lines(txt)[:8]
                a["effective"] = effective_date(txt)
            except RuntimeError as e:
                print("CẢNH BÁO:", e, file=sys.stderr)
                raise
            except Exception as e:  # noqa: BLE001
                a["error"] = str(e)[:100]
        res["articles"].append(a)
        time.sleep(3)
    return res


def selftest():
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    rss = """<rss><channel>
    <item><title>Giá vé phà Cát Lái tăng</title><link>https://x/1</link><pubDate>Thu, 29 Oct 2026 07:00:00 GMT</pubDate><source url="https://tuoitre.vn">Tuổi Trẻ</source></item>
    <item><title>Phà đông khách</title><link>https://x/2</link><pubDate>Fri, 17 Nov 2026 00:00:00 GMT</pubDate><source url="https://vtv.vn">VTV</source></item>
    <item><title>Bài cũ giá vé</title><link>https://x/3</link><pubDate>Wed, 12 Oct 2026 07:00:00 GMT</pubDate><source url="https://a.vn">A</source></item>
    </channel></rss>"""
    items = parse_rss(rss)
    assert len(items) == 3
    got = pick(items, 30, now)
    assert [g["link"] for g in got] == ["https://x/1", "https://x/2"], got  # bài cũ (12/10) bị loại, bài có từ khóa lên đầu
    assert got[0]["keywords"] == ["giá vé"]
    fl = fare_lines("Xe máy 5.000-7.000 đồng/lượt.\nÔ tô dưới 7 chỗ 31.000 - 39.000 đồng\nGhi chú khác")
    assert fl[0]["vehicle"] == "Xe máy" and "5.000" in fl[0]["amounts"], fl
    assert fl[1]["vehicle"] == "Ô tô <7 chỗ", fl
    assert query_for("Cát Lái") == "phà Cát Lái" and query_for("Đò Bình Quới") == "Đò Bình Quới"
    assert effective_date("áp dụng từ ngày 28/10/2026").startswith("từ ngày 28/10")
    print("selftest OK")


def main():
    # Windows consoles may still use a legacy code page; keep Vietnamese output readable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", action="append", default=[])
    ap.add_argument("--csv", help="file ferry_check_449.csv (cột name)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default="news_fare_result.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    import requests
    names = list(a.name)
    if a.csv:
        with open(a.csv, encoding="utf-8-sig") as f:
            names += [r["name"] for r in csv.DictReader(f) if r.get("name")][: a.limit]
    results = []
    for n in names:
        print("-", n)
        results.append(run_route(n, a.days, requests))
        time.sleep(5)
    Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(f"\n{r['name']}: {len(r['articles'])} bài trong {r['window_days']} ngày")
        for x in r["articles"]:
            print(f"  {x['date']} · {x['outlet']} · {', '.join(x['keywords'])}\n    {x['url']}")
            for fl in x["fare_lines"][:4]:
                print(f"    {fl['vehicle']}: {' - '.join(fl['amounts'])}")


if __name__ == "__main__":
    main()
