"""Locate installed descriptions and change only presentation fields."""
import copy
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from market_catalog import MarketCatalog

PLUGIN_ID = "description-zh@personal-zh-tools"
PROTECTED_MARKETS = {"openai-bundled", "openai-primary-runtime", "openai-curated",
                     "openai-api-curated", "personal-zh-tools"}


def codex_executable():
    for path in (shutil.which("codex"), os.environ.get("CODEX_APP_RUNTIME_CLI_PATH")):
        if path and Path(path).is_file():
            return path
    # The Store installation path changes when Codex updates.
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "(Get-AppxPackage -Name OpenAI.Codex).InstallLocation"],
        capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    install = result.stdout.strip()
    path = Path(install) / "app/resources/codex.exe"
    if not install or not path.is_file():
        raise OSError("未找到 Codex。")
    return str(path)


def frontmatter(path):
    with path.open(encoding="utf-8-sig") as stream:
        if stream.readline().strip() != "---":
            raise ValueError("技能说明缺少开头标记。")
        lines = []
        for line in stream:
            if line.rstrip() in ("---", "..."):
                return yaml.safe_load("".join(lines)) or {}
            lines.append(line)
            if len(lines) > 1500:
                break
    raise ValueError("无法读取技能的开头说明。")


def load(data, kind):
    if data is None:
        return {}
    text = data.decode("utf-8-sig")
    obj = (json.loads(text) if kind == "plugin" else yaml.safe_load(text)) or {}
    if not isinstance(obj, dict) or not isinstance(obj.get("interface") or {}, dict):
        raise ValueError("展示字段的格式无法识别。")
    return obj


def skill_yaml(raw, desired):
    # Common cases keep the original comments, order, quoting and unrelated fields.
    text = raw.decode("utf-8-sig") if raw is not None else ""
    node = yaml.compose(text)
    interface_node = next((v for k, v in node.value if k.value == "interface"), None) if node else None
    translated = desired.get("interface", {}).get("short_description")
    quoted = json.dumps(translated, ensure_ascii=False)
    nl = "\r\n" if "\r\n" in text else "\n"
    if not text.strip():
        edited = f"interface:{nl}  short_description: {quoted}{nl}"
    elif isinstance(interface_node, yaml.MappingNode) and translated is not None:
        value = next((v for k, v in interface_node.value if k.value == "short_description"), None)
        if value is not None and isinstance(value, yaml.ScalarNode):
            a, b = value.start_mark.index, value.end_mark.index
            suffix = nl if text[a:b].endswith("\n") else ""
            edited = text[:a] + quoted + suffix + text[b:]
        elif interface_node.value and not interface_node.flow_style:
            mark = interface_node.value[0][0].start_mark
            edited = (text[:mark.index] + "short_description: " + quoted + nl
                      + " " * mark.column + text[mark.index:])
        else:
            edited = ""
    elif interface_node is None and translated is not None:
        edited = text.rstrip("\r\n") + nl + "interface:" + nl + "  short_description: " + quoted + nl
    else:
        edited = ""
    if not edited or yaml.safe_load(edited) != desired:
        edited = yaml.safe_dump(desired, allow_unicode=True, sort_keys=False, width=120,
                                line_break=nl)
    if yaml.safe_load(edited) != desired:
        raise ValueError("更新会影响其他设置，已跳过。")
    return (b"\xef\xbb\xbf" if raw and raw.startswith(b"\xef\xbb\xbf") else b"") + edited.encode()


@dataclass
class Entry:
    path: Path
    kind: str
    name: str
    fallback: str = ""

    def names_in(self, inputs):
        return (self.name,)

    @property
    def fields(self):
        return ("shortDescription", "longDescription") if self.kind == "plugin" else ("short_description",)

    def inputs(self, data, *, fetch_remote=True):
        obj = load(data, self.kind)
        interface = obj.get("interface") or {}
        short = interface.get(self.fields[0]) or self.fallback or obj.get("description")
        values = {}
        if isinstance(short, str) and short.strip():
            values[self.fields[0]] = (self.name, "short", short.strip())
        if self.kind == "plugin":
            long = interface.get("longDescription") or obj.get("description")
            if isinstance(long, str) and long.strip() and (interface.get("longDescription") or long != short):
                values["longDescription"] = (self.name, "long", long.strip())
        return values

    def encode(self, data, doc):
        if self.kind == "skill":
            return skill_yaml(data, doc)
        nl = "\r\n" if data and b"\r\n" in data else "\n"
        bom = b"\xef\xbb\xbf" if data and data.startswith(b"\xef\xbb\xbf") else b""
        return bom + (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").replace("\n", nl).encode()

    def render(self, data, updates):
        doc = load(data, self.kind)
        iface = dict(doc.get("interface") or {})
        if all(iface.get(k) == v for k, v in updates.items()):
            return data
        doc["interface"] = {**iface, **updates}
        return self.encode(data, doc)

    def recover_source(self, current, original, applied):
        if current == applied:
            return original
        if current is None:
            return None
        # A package or user changed other fields since our last write. Take their
        # new document and recover only translations which still match our output.
        obj = load(current, self.kind)
        previous = load(applied, self.kind).get("interface") or {}
        source = load(original, self.kind).get("interface") or {}
        new = copy.deepcopy(obj)
        iface = new.get("interface") or {}
        for k in self.fields:
            if k in previous and iface.get(k) == previous[k] and previous[k] != source.get(k):
                if k in source:
                    iface[k] = source[k]
                else:
                    iface.pop(k, None)
        if new == obj:
            return current
        return self.encode(current, new)


def codex_json(home, *args):
    result = subprocess.run([codex_executable(), *args],
                            env={**os.environ, "CODEX_HOME": str(home)}, cwd=home,
                            capture_output=True, encoding="utf-8", timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise OSError("Codex 插件列表暂时不可用。")
    return json.loads(result.stdout)


def discover(home, extras, markets):
    listing = codex_json(home, "plugin", "list", "--available", "--json")
    plugins = list(listing["installed"])
    installed_ids = {p["pluginId"] for p in plugins}
    plugins.extend(p for p in listing.get("available", [])
                   if p["marketplaceName"] in markets and p["pluginId"] not in installed_ids)
    own_plugin = next((p for p in plugins if p["pluginId"] == PLUGIN_ID), None)
    if not own_plugin or not own_plugin.get("enabled"):
        return {}, [], [], "disabled" if own_plugin else "removed"
    protected = [home / "skills/.system", home / "plugins/cache/openai-bundled",
                 home / ".tmp/bundled-marketplaces"]
    for key in ("ProgramFiles", "ProgramFiles(x86)", "SystemRoot"):
        if os.environ.get(key):
            protected.append(Path(os.environ[key]))
    protected = [p.resolve() for p in protected]
    def allowed(path):
        resolved = path.resolve()
        return not any(resolved.is_relative_to(p) for p in protected)

    entries, issues, market_roots = {}, [], {}
    if markets:
        registered = codex_json(home, "plugin", "marketplace", "list", "--json")
        for market in registered["marketplaces"]:
            name, raw_root = market["name"], Path(market["root"])
            if name not in markets or name in PROTECTED_MARKETS or not raw_root.is_absolute():
                continue
            root = raw_root.resolve()
            catalog = (root / ".agents/plugins/marketplace.json").resolve()
            if catalog.is_relative_to(root) and allowed(catalog) and catalog.is_file():
                market_roots[name] = root
                entries[catalog] = MarketCatalog(catalog, name)

    def add_skill(path):
        try:
            if not allowed(path):
                return
            p = path.resolve()
            meta = (p.parent / "agents/openai.yaml").resolve()
            if not meta.is_relative_to(p.parent) or not allowed(meta) or meta in entries:
                return
            info = frontmatter(p)
            name = info.get("name") or p.parent.name
            summary = (info.get("metadata") or {}).get("short-description") or info.get("description") or ""
            entries[meta] = Entry(meta, "skill", name, summary)
        except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
            issues.append(f"{path}: {type(exc).__name__}")

    def skills_at(base):
        if base.is_file() and base.name == "SKILL.md":
            add_skill(base)
        if not base.is_dir() or not allowed(base):
            return
        # Standalone installers commonly place a junction per skill in the root.
        todo, seen = [base], set()
        while todo:
            folder = todo.pop()
            real = folder.resolve()
            if real in seen or not allowed(real):
                continue
            seen.add(real)
            if (folder / "SKILL.md").is_file():
                add_skill(folder / "SKILL.md")
                continue
            try:
                todo.extend(c for c in folder.iterdir() if c.is_dir()
                            and not c.name.startswith(".") and c.name not in ("node_modules", "__pycache__"))
            except OSError as exc:
                issues.append(f"{folder}: {type(exc).__name__}")

    skill_roots = {home / "skills"}
    if home == (Path.home() / ".codex").resolve():
        skill_roots.add(Path.home() / ".agents/skills")
    for project in map(Path, extras):
        skill_roots.add(project / ".agents/skills")
    protected_plugins = []
    for plugin in plugins:
        name, market = plugin["name"], plugin["marketplaceName"]
        if market in PROTECTED_MARKETS:
            if market != "personal-zh-tools":
                protected_plugins.append(name)
            continue
        version = plugin.get("version")
        cache_base = home / "plugins/cache"
        cache = (cache_base / market / name).resolve()
        if not cache.is_relative_to(cache_base.resolve()):
            continue
        roots = []
        installed = plugin["pluginId"] in installed_ids
        if installed and version and (cache / version).is_dir():
            roots.append(cache / version)
        elif installed and cache.is_dir():
            roots.extend(p for p in cache.iterdir() if p.is_dir())
        src = plugin.get("source") or {}
        market_root = market_roots.get(market)
        if market_root is not None and src.get("source") == "local" and src.get("path"):
            source = Path(src["path"]).resolve()
            if source.is_relative_to(market_root):
                roots.append(source)
        for root in roots:
            try:
                root = root.resolve()
                if not (root.is_relative_to(cache) or
                        (market_root is not None and root.is_relative_to(market_root))):
                    continue
                manifest = (root / ".codex-plugin/plugin.json").resolve()
                if not allowed(manifest) or not manifest.is_relative_to(root) or not manifest.is_file():
                    continue
                data = load(manifest.read_bytes(), "plugin")
                entries[manifest] = Entry(manifest, "plugin", name)
                if not installed:
                    continue
                declared = data.get("skills", "./skills")
                for rel in (declared if isinstance(declared, list) else [declared]):
                    if isinstance(rel, str):
                        folder = (root / rel).resolve()
                        if folder.is_relative_to(root):
                            skill_roots.add(folder)
            except (OSError, ValueError, TypeError) as exc:
                issues.append(f"{root}: {type(exc).__name__}")
    for base in sorted(skill_roots):
        skills_at(base)
    return entries, issues, protected_plugins, "enabled"
