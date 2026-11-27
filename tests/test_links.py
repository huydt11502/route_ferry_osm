from ferrycheck.links import build_links
from ferrycheck.models import Route


def test_links_are_generated_and_encoded():
    links = build_links(Route("way/1", "Bình Khánh", "10.1,106.2"))
    assert links["link_osm"].endswith("way/1")
    assert "ph%C3%A0+B%C3%ACnh" in links["link_google_news"]
