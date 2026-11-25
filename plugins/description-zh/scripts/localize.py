"""Windows worker and controls for Description ZH."""
import argparse
import contextlib
import datetime
import hashlib
import json
import msvcrt
import os
import sqlite3
import stat
import sys
import tempfile
import time
from pathlib import Path

import yaml

from metadata import PROTECTED_MARKETS, codex_executable, codex_json, discover
from market_watch import market_notifications
from translate import is_chinese, translate


HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
STATE = HOME / "description-zh"
INTERVAL = 60
LEGACY_MARKETS = ("academic-research-skills", "diagram-design", "openai-plugins-local")


def timestamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def database():
    STATE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / "translations.sqlite3", timeout=12)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS translations(key TEXT PRIMARY KEY, text TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS edits(path TEXT PRIMARY KEY, original BLOB, applied BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS pending_edits(path TEXT PRIMARY KEY, original BLOB, applied BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS projects(path TEXT PRIMARY KEY);
    """)
    # Existing installations already selected the original three markets.
    with db:
        legacy = bool(db.execute("SELECT 1 FROM settings WHERE key='lastScan'").fetchone())
        db.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('marketNames',?)",
                   (json.dumps(LEGACY_MARKETS if legacy else []),))
    return db


def setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def save_setting(db, key, value):
    with db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))


class Busy(Exception):
    pass


@contextlib.contextmanager
def locked(name):
    with (STATE / (name + ".lock")).open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise Busy(name) from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def current_bytes(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def replace(path, expected, new):
    if path.resolve() != path or current_bytes(path) != expected:
        raise ValueError("文件已变化，将重新检查。")
    if expected == new:
        return
    if new is None:
        path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".description-zh-", delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(new)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        if path.resolve() != path or current_bytes(path) != expected:
            raise ValueError("文件已变化，将重新检查。")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def key_id(key):
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()


def readable_error(exc):
    if type(exc) == ValueError and "。" in str(exc) and len(str(exc)) < 140:
        return str(exc)
    return type(exc).__name__


def active(db):
    return not (setting(db, "paused", True) or setting(db, "stopRequested", False))


def selected_markets(db):
    return setting(db, "marketNames", [])


def registered_markets():
    listing = codex_json(HOME, "plugin", "marketplace", "list", "--json")
    return [row["name"] for row in listing["marketplaces"] if row["name"] not in PROTECTED_MARKETS]


def finish_writes(db):
    # Recover a completed rename if the process stopped before its SQLite commit.
    for path, original, applied in db.execute("SELECT path,original,applied FROM pending_edits").fetchall():
        live = current_bytes(Path(path))
        with db:
            if live == applied:
                db.execute("INSERT OR REPLACE INTO edits VALUES (?,?,?)", (path, original, applied))
            db.execute("DELETE FROM pending_edits WHERE path=?", (path,))


def scan(db, *, preview=False):
    with locked("scan"):
        if not preview and not active(db):
            return {"paused": True}
        if not preview:
            finish_writes(db)
        projects = [row[0] for row in db.execute("SELECT path FROM projects")]
        entries, issues, protected, plugin_state = discover(HOME, projects, set(selected_markets(db)))
        if plugin_state != "enabled":
            report = {"checked": timestamp(), "pluginState": plugin_state}
            if not preview:
                save_setting(db, "lastScan", report)
            return report
        snapshots = []
        all_keys = set()
        for path, entry in entries.items():
            try:
                current = current_bytes(path)
                saved = db.execute("SELECT original,applied FROM edits WHERE path=?", (str(path),)).fetchone()
                source = entry.recover_source(current, *saved) if saved else current
                inputs = entry.inputs(source, fetch_remote=not preview)
                snapshots.append((entry, current, source, inputs))
                all_keys.update(inputs.values())
            except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
                issues.append(f"{entry.name}: {readable_error(exc)}")

        translated = {}
        pending = []
        for key in sorted(all_keys):
            if is_chinese(key[2]):
                translated[key] = key[2]
            else:
                row = db.execute("SELECT text FROM translations WHERE key=?", (key_id(key),)).fetchone()
                if row:
                    translated[key] = row[0]
                else:
                    pending.append(key)

        if preview:
            return {"preview": True, "marketplaces": sorted(selected_markets(db)),
                    "filesWithDescriptions": sum(bool(inputs) for _, _, _, inputs in snapshots),
                    "untranslatedTexts": len(pending), "protectedPlugins": protected, "issues": issues}

        # The input is display metadata only. Group identical source/cache copies.
        fresh = 0
        for i in range(0, len(pending), 8):
            if not active(db):
                return {"paused": True}
            batch = pending[i:i + 8]
            try:
                new = translate(HOME, batch)
                translated.update(new)
                with db:
                    db.executemany("INSERT OR REPLACE INTO translations VALUES (?,?)",
                                   [(key_id(k), v) for k, v in new.items()])
                fresh += len(new)
                if len(new) != len(batch):
                    issues.append("等待重新翻译：" + "、".join(k[0] for k in batch if k not in new))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                issues.append("翻译服务：" + readable_error(exc))
                break

        changed = 0
        ready = {"plugin": set(), "skill": set()}
        for entry, current, source, inputs in snapshots:
            if not active(db):
                return {"paused": True}
            if not inputs:
                continue
            try:
                updates = {field: translated[k] for field, k in inputs.items() if k in translated}
                if not updates:
                    continue
                new = entry.render(source, updates)
                if current != new:
                    # Keep the previous backup until the new file is on disk.
                    if current_bytes(entry.path) != current:
                        raise ValueError("文件已变化，将重新检查。")
                    with db:
                        db.execute("INSERT OR REPLACE INTO pending_edits VALUES (?,?,?)",
                                   (str(entry.path), source, new))
                    replace(entry.path, current, new)
                    with db:
                        db.execute("INSERT OR REPLACE INTO edits VALUES (?,?,?)",
                                   (str(entry.path), source, new))
                        db.execute("DELETE FROM pending_edits WHERE path=?", (str(entry.path),))
                    changed += 1
                elif source != current and current_bytes(entry.path) == current:
                    with db:
                        db.execute("UPDATE edits SET original=?,applied=? WHERE path=? AND "
                                   "(original IS NOT ? OR applied IS NOT ?)",
                                   (source, new, str(entry.path), source, new))
                ready[entry.kind].update(entry.names_in(updates))
            except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
                issues.append(f"{entry.name}: {readable_error(exc)}")
        report = {"checked": timestamp(), "pluginDescriptions": sorted(ready["plugin"]),
                  "skillDescriptions": sorted(ready["skill"]), "newTexts": fresh,
                  "filesChanged": changed, "untranslatedTexts": len(all_keys - translated.keys()),
                  "protectedPlugins": protected, "issues": issues}
        save_setting(db, "lastScan", report)
        return report


def restore(db):
    save_setting(db, "paused", True)
    skipped = []
    count = 0
    with locked("scan"):
        finish_writes(db)
        for path, original, applied in db.execute("SELECT path,original,applied FROM edits").fetchall():
            p = Path(path)
            try:
                live = current_bytes(p)
                if live is None or live == original:
                    pass
                elif live == applied:
                    replace(p, applied, original)
                    count += 1
                else:
                    skipped.append(path)
                    continue
                with db:
                    db.execute("DELETE FROM edits WHERE path=?", (path,))
            except (OSError, ValueError):
                skipped.append(path)
    return {"paused": True, "restoredFiles": count, "changedSinceTranslation": skipped}


def watch(db):
    with locked("worker"), market_notifications(HOME) as market_changed:
        save_setting(db, "workerPid", os.getpid())
        failures = 0
        try:
            while not setting(db, "stopRequested", False):
                save_setting(db, "heartbeat", timestamp())
                revision = setting(db, "wake", 0)
                report = {}
                if active(db):
                    try:
                        report = scan(db)
                        if report.get("pluginState") == "removed":
                            return
                    except Busy:
                        pass
                    except Exception as exc:
                        report = {"checked": timestamp(), "issues": [readable_error(exc)]}
                        save_setting(db, "lastScan", report)
                failures = min(failures + 1, 5) if report.get("issues") else 0
                delay = INTERVAL * (2 ** failures)
                for _ in range(delay // 5):
                    if (market_changed(5) or setting(db, "stopRequested", False)
                            or revision != setting(db, "wake", 0)):
                        break
        finally:
            save_setting(db, "workerPid", None)


def main():
    global HOME, STATE
    parser = argparse.ArgumentParser(description="管理 Codex 插件和技能的中文简介。")
    parser.add_argument("action", choices=("preview", "scan", "watch", "status", "pause", "resume",
                                          "stop", "restore", "markets", "projects", "codex-path"))
    parser.add_argument("--project", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--market", action="append", metavar="NAME")
    parser.add_argument("--clear-markets", action="store_true")
    parser.add_argument("--remove-project", type=Path)
    args = parser.parse_args()
    if args.home:
        HOME = args.home.resolve()
        STATE = HOME / "description-zh"
    if args.action == "codex-path":
        print(codex_executable())
        return
    if (args.market or args.clear_markets) and args.action != "markets":
        parser.error("--market and --clear-markets require the markets command")
    if args.market and args.clear_markets:
        parser.error("--clear-markets cannot be combined with --market")
    if args.project and args.action not in ("scan", "resume", "projects"):
        parser.error("--project requires scan, resume, or projects")
    if args.remove_project and (args.action != "projects" or args.project):
        parser.error("--remove-project requires projects and cannot be combined with --project")
    with contextlib.closing(database()) as db:
        if args.project:
            root = args.project.resolve()
            if not root.is_dir():
                parser.error("项目目录不存在。")
            with db:
                db.execute("INSERT OR IGNORE INTO projects VALUES (?)", (str(root),))
            save_setting(db, "wake", time.time_ns())
        if args.action == "watch":
            return watch(db)
        if args.action in ("scan", "preview"):
            result = scan(db, preview=args.action == "preview")
        elif args.action == "restore":
            result = restore(db)
        elif args.action == "projects":
            if args.remove_project:
                with db:
                    db.execute("DELETE FROM projects WHERE path=?", (str(args.remove_project.resolve()),))
                save_setting(db, "wake", time.time_ns())
            result = {"projects": [row[0] for row in db.execute("SELECT path FROM projects ORDER BY path")]}
        elif args.action == "markets":
            available = registered_markets()
            if args.market is not None or args.clear_markets:
                selected = sorted(set(args.market or []))
                unknown = set(selected) - set(available)
                if unknown:
                    parser.error("不可用或受保护的市场：" + ", ".join(sorted(unknown)))
                save_setting(db, "marketNames", selected)
                save_setting(db, "wake", time.time_ns())
            result = {"available": available, "selected": sorted(selected_markets(db))}
        elif args.action in ("pause", "resume", "stop"):
            save_setting(db, "paused", args.action != "resume")
            if args.action in ("resume", "stop"):
                save_setting(db, "stopRequested", args.action == "stop")
            save_setting(db, "wake", time.time_ns())
            result = {"paused": not active(db)}
        else:
            try:
                with locked("worker"):
                    running = False
            except Busy:
                running = True
            result = {"workerRunning": running, "paused": not active(db),
                      "heartbeat": setting(db, "heartbeat"), "lastScan": setting(db, "lastScan"),
                      "marketplaces": sorted(selected_markets(db)),
                      "backups": db.execute("SELECT COUNT(*) FROM edits").fetchone()[0]}
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Busy:
        if sys.stdout:
            print("当前已有一次检查正在运行。")
        sys.exit(2)
    except (OSError, ValueError) as exc:
        if sys.stderr:
            print(readable_error(exc), file=sys.stderr)
        sys.exit(1)
