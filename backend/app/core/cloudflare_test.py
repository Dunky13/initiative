import pytest

from app.core import cloudflare


@pytest.mark.parametrize(
    ("client", "connecting", "visitor"),
    [
        ("173.245.48.1", "198.51.100.20", "198.51.100.20"),
        ("2606:4700::1", " 2001:db8::1 ", "2001:db8::1"),
        ("162.158.1.2", "2001:4860:0:0:0:0:0:8888", "2001:4860::8888"),
        ("162.158.1.2", "", None),
        ("162.158.1.2", "garbage", None),
        ("203.0.113.7", "198.51.100.20", None),
        ("10.0.0.5", "198.51.100.20", None),
        (None, "198.51.100.20", None),
        ("testclient", "198.51.100.20", None),
    ],
)
def test_only_cloudflares_edge_names_a_visitor(client, connecting, visitor):
    assert cloudflare.visitor(client, connecting) == visitor
