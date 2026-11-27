from urllib.parse import quote_plus

from .models import Route


def build_links(route: Route) -> dict[str, str]:
    maps_query = route.toa_do.strip()
    maps = f"https://www.google.com/maps/search/?api=1&query={quote_plus(maps_query)}" if maps_query else ""
    query = route.query
    links = {"link_osm": f"https://www.openstreetmap.org/{route.osm_id}"}
    links["link_google_maps"] = maps
    if not query:
        return links | {"link_google_search_phi": "", "link_google_news": "", "link_facebook": "", "link_instagram": ""}
    links.update({
        "link_google_search_phi": "https://www.google.com/search?q=" + quote_plus(f"{query} giá vé"),
        "link_google_news": "https://news.google.com/search?q=" + quote_plus(query) + "&hl=vi&gl=VN&ceid=VN:vi",
        "link_facebook": "https://www.google.com/search?q=" + quote_plus(f'site:facebook.com "{query}"'),
        "link_instagram": "https://www.google.com/search?q=" + quote_plus(f'site:instagram.com "{query}"'),
    })
    return links
