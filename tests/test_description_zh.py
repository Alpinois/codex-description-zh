import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/description-zh/scripts"
sys.path.insert(0, str(SCRIPTS))

import localize
from market_catalog import MarketCatalog
from metadata import Entry, discover
from translate import endpoint_settings, translate


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.addCleanup(patch.stopall)
        patch.multiple(localize, HOME=self.home, STATE=self.home / "description-zh").start()
        self.db = localize.database()
        self.addCleanup(self.db.close)

    def test_new_profile_does_not_translate_until_enabled(self):
        with patch.object(localize, "discover") as discovery, patch.object(localize, "translate") as model:
            self.assertEqual(localize.scan(self.db), {"paused": True})
        discovery.assert_not_called()
        model.assert_not_called()

    def test_fresh_profile_never_adopts_legacy_markets_after_scan(self):
        localize.save_setting(self.db, "lastScan", {"filesChanged": 0})
        with contextlib.closing(localize.database()) as reloaded:
            self.assertEqual(localize.selected_markets(reloaded), [])

    def test_existing_profile_keeps_legacy_market_selection_on_upgrade(self):
        with self.db:
            self.db.execute("DELETE FROM settings WHERE key='marketNames'")
        localize.save_setting(self.db, "lastScan", {"filesChanged": 0})
        with contextlib.closing(localize.database()) as reloaded:
            self.assertEqual(tuple(localize.selected_markets(reloaded)), localize.LEGACY_MARKETS)

    def test_preview_applies_nothing_and_uses_no_network(self):
        path = self.home / ".agents/plugins/marketplace.json"
        path.parent.mkdir(parents=True)
        original = b'{"plugins":[{"name":"tool","source":{"source":"url","url":"https://github.com/test/tool"},"interface":{"shortDescription":"Help with planning."}}]}'
        path.write_bytes(original)
        entries = {path: MarketCatalog(path, "test")}
        with patch.object(localize, "discover", return_value=(entries, [], [], "enabled")), \
                patch("market_catalog.github_manifest") as remote, patch.object(localize, "translate") as model:
            result = localize.scan(self.db, preview=True)
        model.assert_not_called()
        remote.assert_not_called()
        self.assertEqual(result["untranslatedTexts"], 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertIsNone(localize.setting(self.db, "lastScan"))

    def test_scan_update_and_restore_only_display_fields(self):
        root = self.home / "skills/test"
        root.mkdir(parents=True)
        skill = root / "SKILL.md"
        source = b"---\nname: test\ndescription: Help plan your study time.\n---\nEnglish instructions.\n"
        skill.write_bytes(source)
        path = root / "agents/openai.yaml"
        entry = Entry(path, "skill", "test", "Help plan your study time.")
        localize.save_setting(self.db, "paused", False)
        with patch.object(localize, "discover", return_value=({path: entry}, [], [], "enabled")), \
                patch.object(localize, "translate", side_effect=lambda home, keys: {k: "帮你安排学习时间。" for k in keys}) as model:
            self.assertEqual(localize.scan(self.db)["filesChanged"], 1)
            self.assertIn("帮你安排学习时间", path.read_text(encoding="utf8"))
            self.assertEqual(localize.scan(self.db)["filesChanged"], 0)
            self.assertEqual(model.call_count, 1)
        self.assertEqual(localize.restore(self.db)["restoredFiles"], 1)
        self.assertFalse(path.exists())
        self.assertEqual(skill.read_bytes(), source)

    def test_restore_leaves_user_edit_and_backup_intact(self):
        path = self.home / "plugin.json"
        original = b"original"
        applied = b"translated"
        with self.db:
            self.db.execute("INSERT INTO edits VALUES (?,?,?)", (str(path), original, applied))
        path.write_bytes(b"edited meanwhile")
        self.assertEqual(localize.restore(self.db)["changedSinceTranslation"], [str(path)])
        self.assertEqual(path.read_bytes(), b"edited meanwhile")
        self.assertEqual(self.db.execute("SELECT original FROM edits").fetchone()[0], original)

    def test_only_selected_registered_market_reaches_uninstalled_plugin(self):
        marketplace = self.home / "owned-source"
        catalog = marketplace / ".agents/plugins/marketplace.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_text('{"name":"example","plugins":[]}', encoding="utf8")
        manifest = marketplace / "plugin/.codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name":"test","description":"Help with planning."}', encoding="utf8")
        own = {"pluginId": "description-zh@personal-zh-tools", "name": "description-zh", "marketplaceName": "personal-zh-tools", "enabled": True}
        item = {"pluginId": "test@example", "name": "test", "marketplaceName": "example",
                "source": {"source": "local", "path": str(manifest.parent.parent)}}
        listing = {"installed": [own], "available": [item]}
        markets = {"marketplaces": [{"name": "example", "root": str(marketplace)}]}
        with patch("metadata.codex_json", side_effect=lambda home, *args: markets if args[1] == "marketplace" else listing):
            entries, _, _, _ = discover(self.home, [], {"example"})
            unselected, _, _, _ = discover(self.home, [], set())
        self.assertEqual(set(entries), {manifest, catalog})
        self.assertFalse(unselected)


class ProviderTests(unittest.TestCase):
    def test_default_openai_key_does_not_leak_to_custom_provider(self):
        config = {"model": "example", "model_provider": "custom",
                  "model_providers": {"custom": {"base_url": "https://model.example/v1"}}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-credential"}, clear=True):
            url, _, headers = endpoint_settings(config)
        self.assertEqual(url, "https://model.example/v1/responses")
        self.assertNotIn("Authorization", headers)

    def test_dedicated_provider_uses_only_dedicated_key(self):
        values = {"DESCRIPTION_ZH_BASE_URL": "http://127.0.0.1:9999/v1",
                  "DESCRIPTION_ZH_MODEL": "local", "DESCRIPTION_ZH_API_KEY": "dedicated"}
        with patch.dict(os.environ, values, clear=True):
            url, model, headers = endpoint_settings({})
        self.assertEqual(url, "http://127.0.0.1:9999/v1/responses")
        self.assertEqual(model, "local")
        self.assertEqual(headers["Authorization"], "Bearer dedicated")

    def test_rejects_credentials_and_queries_in_url(self):
        for base in ("https://user:pass@model.example/v1", "https://model.example/v1?token=test"):
            with self.subTest(base=base), patch.dict(os.environ, {"DESCRIPTION_ZH_BASE_URL": base,
                                                                 "DESCRIPTION_ZH_MODEL": "test"}, clear=True):
                with self.assertRaises(ValueError):
                    endpoint_settings({})

    def test_model_results_are_validated(self):
        keys = [("example", "short", "Manage notes.")]
        data = '[{"id":false,"text":"忽略这一项"},{"id":0,"text":"整理笔记。"}]'
        with patch("translate.model_reply", return_value=data):
            self.assertEqual(translate(Path("."), keys), {keys[0]: "整理笔记。"})


if __name__ == "__main__":
    unittest.main()
