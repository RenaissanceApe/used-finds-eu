"""The probe's page-shape diagnostics.

These decide whether a broken source is fixable with a selector at all. Getting
this wrong sends someone hunting for CSS on a page that never contained the
results, so the distinction is worth pinning down.
"""

import importlib.util
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

_PROBE = Path(__file__).resolve().parents[2] / "scripts" / "probe_site.py"
_spec = importlib.util.spec_from_file_location("probe_site", _PROBE)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


SHELL = """<!doctype html><html><head><script src="/_next/static/x.js"></script></head>
<body><div id="__next"><div class="card"></div><div class="card"></div><div class="card"></div>
</div></body></html>"""

RENDERED = """<!doctype html><html><body>
<div class="row"><a href="/1">Apple iPhone 13</a><span>€430</span></div>
<div class="row"><a href="/2">iPhone 12 mini</a><span>€245</span></div>
</body></html>"""


def test_client_rendered_shell_is_reported_as_unfixable_by_selectors(capsys):
    probe.describe_page_shape(SHELL, "iphone")
    out = capsys.readouterr().out
    assert "NO" in out
    assert "server did not render the results" in out
    assert "Next.js" in out


def test_server_rendered_page_is_reported_as_fixable(capsys):
    probe.describe_page_shape(RENDERED, "iphone")
    out = capsys.readouterr().out
    assert "yes, 2 times" in out
    assert "server did not render" not in out


def test_term_matching_ignores_case():
    # "iPhone" in the page, "iphone" on the command line — the same thing.
    probe.describe_page_shape("<html>Apple IPHONE 13</html>", "iPhone")


@pytest.mark.parametrize("html,expected", [
    (SHELL, "div.card"),
    ('<div><p class="a">x</p><p class="a">y</p></div>', None),   # only 2, below the floor
])
def test_repeated_elements_needs_a_real_repetition(html, expected):
    found = probe.repeated_elements(BeautifulSoup(html, "lxml"))
    if expected:
        assert any(line.startswith(expected) for line in found)
    else:
        assert found == []
