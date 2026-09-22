from unittest.mock import patch

from src.config import settings
from src.market.client import MarketClient


def _client_with_probe_responses(responses: dict[str, object]) -> MarketClient:
    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client._pool = None
    client.licence = "LICENCE-TEST-KEY"
    client.sample_only = False
    client.status = "unchecked"

    def fake_get(path: str):
        for code, payload in responses.items():
            if path.endswith(f"/{code}"):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise RuntimeError(f"unexpected path {path}")

    with patch.object(client, "_get", side_effect=fake_get):
        client._probe()
    return client


def test_probe_all_errors_not_sample_only():
    err = Exception("quota")
    c = _client_with_probe_responses(
        {
            "000001": err,
            "600038": err,
            "002230": err,
        }
    )
    assert c.sample_only is False
    assert c.status == "probe-failed"


def test_probe_distinct_prices_is_live():
    c = _client_with_probe_responses(
        {
            "000001": [{"p": 11.0}],
            "600038": [{"p": 26.0}],
            "002230": [{"p": 45.0}],
        }
    )
    assert c.sample_only is False
    assert c.status == "live"


def test_probe_same_price_is_sample_only():
    c = _client_with_probe_responses(
        {
            "000001": [{"p": 9.9}],
            "600038": [{"p": 9.9}],
            "002230": [{"p": 9.9}],
        }
    )
    assert c.sample_only is True
    assert c.status == "sample-only"


def test_demo_licence_is_sample_only_without_probe():
    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client._pool = None
    client.licence = settings.demo_licence
    client.sample_only = False
    client.status = "unchecked"
    with patch("src.market.clock.configured_clock_dir", return_value=None):
        client._probe()
    assert client.sample_only is True
    assert client.status == "demo-licence"
