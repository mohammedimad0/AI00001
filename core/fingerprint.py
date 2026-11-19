"""Fingerprinting: make messages that differ only in IDs, IPs or numbers look identical.

"Login failed for user root from 175.45.176.9 port 40211"
"Login failed for user admin from 175.45.176.88 port 51990"
both become
"login failed for user <user> from <ip> port <num>"  -> same hash
"""
from __future__ import annotations

import hashlib
import re

# Order matters: specific patterns first, plain numbers last
_RULES = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\brequest_id=\S+", re.I), "request_id=<id>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"(\buser\s+)\S+", re.I), r"\1<user>"),
    (re.compile(r"/\d+(?=/|\b)"), "/<id>"),
    (re.compile(r"\d+(\.\d+)?"), "<num>"),
]


def make_template(message: str) -> str:
    t = message.lower()
    for pattern, repl in _RULES:
        t = pattern.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(error_type: str, service: str, message: str) -> tuple[str, str]:
    template = make_template(message)
    digest = hashlib.sha1(f"{error_type}|{service}|{template}".encode()).hexdigest()[:12]
    return template, digest
