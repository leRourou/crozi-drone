import pytest

from api.logfmt import kv, short_browser


def test_kv_formats_values_readably():
    line = kv("stats", sid="abcd1234", rt=1.0, peak=None, mic="Built-in Mic", ok=True)
    assert line == 'event=stats sid=abcd1234 rt=1.00 peak=- mic="Built-in Mic" ok=true'


@pytest.mark.parametrize(
    ("ua", "expected"),
    [
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Mobile Safari/537.36",
            "Chrome/131 Android",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
            "Safari/18 iPhone",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
            "Firefox/133 Linux",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0",
            "Edge/131 Windows",
        ),
        ("", "? ?"),
    ],
)
def test_short_browser(ua, expected):
    assert short_browser(ua) == expected
