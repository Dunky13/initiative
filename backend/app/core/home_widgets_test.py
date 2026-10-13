"""The server's list of home widgets is the client's.

A layout listing is checked against :mod:`app.core.home_widgets` on the way in
and drawn by ``frontend/src/lib/home/widgetTypes.ts`` on the way out, so the two
name the same widgets with the same smallest sizes and the same once-only rule.
"""

import re
from pathlib import Path

import pytest

from app.core.home_widgets import HOME_WIDGET_SPECS

pytestmark = pytest.mark.always

WIDGET_TYPES_TS = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "home"
    / "widgetTypes.ts"
)


def _client_widgets() -> dict[str, dict[str, object]]:
    source = WIDGET_TYPES_TS.read_text()
    sizes = source[source.index("HOME_WIDGET_SIZES") :]
    found = {}
    for match in re.finditer(r"^\s*(\w+): \{([^}]*)\},?\s*$", sizes, re.MULTILINE):
        fields = dict(re.findall(r"(\w+): (\w+)", match.group(2)))
        found[match.group(1)] = {
            "min_w": int(fields["minW"]),
            "min_h": int(fields["minH"]),
            "single": fields.get("single") == "true",
        }
    return found


def test_the_server_and_the_client_know_the_same_widgets():
    client = _client_widgets()
    assert client, f"no widget sizes read from {WIDGET_TYPES_TS}"
    server = {
        name: {"min_w": spec.min_w, "min_h": spec.min_h, "single": spec.single}
        for name, spec in HOME_WIDGET_SPECS.items()
    }
    assert server == client
