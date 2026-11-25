"""Translate descriptions exposed by a marketplace index, including remote-only entries."""
import copy
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath


FIELDS = {"shortDescription": "short", "longDescription": "long"}


@lru_cache(maxsize=128)
def github_manifest(url, hour):
    # Request only the public manifest, anonymously. Never check out or run a package.
    request = urllib.request.Request(url, headers={"User-Agent": "Codex-Description-ZH"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            body = response.read(256 * 1024 + 1)
        if len(body) <= 256 * 1024:
            doc = json.loads(body)
            if isinstance(doc, dict) and isinstance(doc.get("interface", {}), dict):
                return doc
    except (OSError, ValueError):
        pass
    return {}


def remote_texts(row):
    source = row.get("source") or {}
    if source.get("source") not in ("url", "git-subdir"):
        return {}
    match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?", source.get("url", ""))
    subdir = PurePosixPath(source.get("path") or ".")
    if not match or subdir.is_absolute() or ".." in subdir.parts:
        return {}
    ref = source.get("sha") or source.get("ref") or "HEAD"
    manifest = subdir / ".codex-plugin/plugin.json"
    url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        *match.groups(), urllib.parse.quote(ref, safe=""), urllib.parse.quote(str(manifest)))
    doc = github_manifest(url, int(time.time() // 3600))
    iface = doc.get("interface", {})
    return {field: iface.get(field) or doc.get("description") for field in FIELDS}


def rows(doc):
    return {p["name"]: p for p in doc.get("plugins", []) if isinstance(p, dict) and p.get("name")}


def encode(doc, previous):
    newline = "\r\n" if b"\r\n" in previous else "\n"
    data = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").replace("\n", newline).encode()
    return (b"\xef\xbb\xbf" if previous.startswith(b"\xef\xbb\xbf") else b"") + data


@dataclass
class MarketCatalog:
    path: Path
    name: str
    kind = "plugin"

    def names_in(self, inputs):
        return {name for name, field in inputs}

    def inputs(self, data, *, fetch_remote=True):
        if not data:
            return {}
        keys = {}
        for name, row in rows(json.loads(data)).items():
            interface = row.get("interface") or {}
            if not isinstance(interface, dict):
                continue
            fallback = remote_texts(row) if fetch_remote and not all(interface.get(f) for f in FIELDS) else {}
            for field, style in FIELDS.items():
                value = interface.get(field) or fallback.get(field)
                if isinstance(value, str) and value.strip():
                    keys[name, field] = (name, style, value.strip())
        return keys

    def render(self, data, updates):
        doc = json.loads(data)
        entries = rows(doc)
        changed = False
        for (name, field), value in updates.items():
            interface = entries[name].get("interface") or {}
            entries[name]["interface"] = interface
            if interface.get(field) != value:
                interface[field] = value
                changed = True
        return encode(doc, data) if changed else data

    def recover_source(self, current, original, applied):
        if current == applied:
            return original
        if not current or not original:
            return current
        doc = json.loads(current)
        previous = rows(json.loads(applied))
        originals = rows(json.loads(original))
        updated = copy.deepcopy(doc)
        for name, row in rows(updated).items():
            earlier, source = previous.get(name, {}), originals.get(name, {})
            if row.get("source") != earlier.get("source") or not source:
                continue
            interface = row.get("interface") or {}
            for field in FIELDS:
                old_value = (earlier.get("interface") or {}).get(field)
                raw_value = (source.get("interface") or {}).get(field)
                if old_value and interface.get(field) == old_value and raw_value != old_value:
                    if raw_value is None:
                        interface.pop(field)
                    else:
                        interface[field] = raw_value
            if not interface and "interface" not in source:
                row.pop("interface", None)
        return encode(updated, current) if updated != doc else current
