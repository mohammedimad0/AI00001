"""IP -> country lookup.

Uses MaxMind GeoLite2 if the database file is present (free signup at maxmind.com,
download GeoLite2-Country.mmdb into data/). Otherwise falls back to a small
built-in table so the demo works offline.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "GeoLite2-Country.mmdb"

_FALLBACK = {
    "175.45.176.0/22": "KP",   # North Korea
    "49.36.0.0/14": "IN",      # India (Reliance Jio)
    "8.8.8.0/24": "US",
}
_NETWORKS = [(ipaddress.ip_network(n), c) for n, c in _FALLBACK.items()]

_reader = None
try:
    if _DB_PATH.exists():
        import geoip2.database  # pip install geoip2
        _reader = geoip2.database.Reader(str(_DB_PATH))
except Exception:
    _reader = None


def country_of(ip: str | None) -> str | None:
    if not ip:
        return None
    if _reader is not None:
        try:
            return _reader.country(ip).country.iso_code
        except Exception:
            pass
    addr = ipaddress.ip_address(ip)
    for net, code in _NETWORKS:
        if addr in net:
            return code
    return "ZZ"  # unknown
