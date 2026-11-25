"""Windows release smoke test with a clean CODEX_HOME and local mock Responses API."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

source = Path(__file__).resolve().parents[1]
workspace = tempfile.TemporaryDirectory(prefix="Description ZH test ")
scratch = Path(workspace.name)
print("Temporary isolated profile", scratch, flush=True)
home = scratch / "Codex home"
home.mkdir()
package = scratch / "Release copy"
shutil.copytree(source, package, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
fixtures = home / "marketplaces" / "test-market"
fixture_catalog = fixtures / ".agents/plugins/marketplace.json"
fixture_catalog.parent.mkdir(parents=True)
fixture_manifest = fixtures / "plugins/test-tool/.codex-plugin/plugin.json"
fixture_manifest.parent.mkdir(parents=True)
fixture_catalog.write_text(json.dumps({"name": "test-market", "plugins": [
    {"name": "test-tool", "source": {"source": "local", "path": "./plugins/test-tool"},
     "interface": {"shortDescription": "Plan courses."}}]}), encoding="utf-8")
fixture_manifest.write_text(json.dumps({"name": "test-tool", "version":"1.0.0",
    "description": "Plan courses.", "interface": {"shortDescription": "Plan courses.",
    "longDescription": "Schedule classes and see your progress."}}), encoding="utf-8")
original_market = fixture_catalog.read_bytes()
original_manifest = fixture_manifest.read_bytes()
requests = []

class Translator(BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.path == "/v1/responses"
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        rows = json.loads(request["input"])
        requests.extend(rows)
        data = [{"id":row["id"],"text":"帮你安排课程并查看进度。"} for row in rows]
        response = json.dumps({"output":[{"content":[{"type":"output_text","text":json.dumps(data)}]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(response)))
        self.end_headers()
        self.wfile.write(response)
    def log_message(self,*args):
        return

server = ThreadingHTTPServer(("127.0.0.1",0),Translator)
threading.Thread(target=server.serve_forever,daemon=True).start()
env = {**os.environ, "CODEX_HOME": str(home),
       "DESCRIPTION_ZH_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
       "DESCRIPTION_ZH_MODEL": "test-model"}
for key in ("DESCRIPTION_ZH_API_KEY", "OPENAI_API_KEY"):
    env.pop(key, None)

def invoke(args):
    print("Running", Path(args[0]).name, flush=True)
    p = subprocess.run(args, cwd=package, env=env, text=True, encoding="utf-8",
                       capture_output=True, timeout=95)
    if p.returncode:
        print(p.stdout,p.stderr,flush=True)
        p.check_returncode()
    return p.stdout.strip()

powershell = shutil.which("powershell") or shutil.which("pwsh")
def ps(filename,*args):
    return invoke([powershell,"-NoProfile","-ExecutionPolicy","Bypass","-File",str(package/filename),*args])
def manage(*a):
    return json.loads(ps("manage.ps1",*a))


def catalog_display(codex):
    initialize = {"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "description-zh-smoke", "version": "1"},
        "capabilities": {"experimentalApi": True}}}
    list_plugins = {"id": 2, "method": "plugin/list", "params": {"cwds": [str(package)]}}
    proc = subprocess.Popen([codex, "app-server", "--listen", "stdio://"], cwd=package,
                            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        for message in (initialize, {"method": "initialized"}, list_plugins):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
            if "id" not in message:
                continue
            for line in proc.stdout:
                response = json.loads(line)
                if response.get("id") == message["id"]:
                    break
        markets = response["result"]["marketplaces"]
        market = next(m for m in markets if m["name"] == "test-market")
        plugin = next(p for p in market["plugins"] if p["name"] == "test-tool")
        return plugin["interface"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def skill(name):
    folder = home/"skills"/name
    folder.mkdir(parents=True)
    path = folder/"SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: Schedule lessons and study breaks.\n---\nLeave this English instruction intact.\n",encoding="utf-8")
    return path, folder/"agents/openai.yaml"

started = False
try:
    print(ps("enable.ps1","-Python",sys.executable),flush=True)
    codex = ps("manage.ps1","codex-path")
    assert "paused" in manage("scan")
    print(invoke([codex,"plugin","marketplace","add",str(fixtures)]),flush=True)
    assert manage("markets","-Market","test-market")["selected"] == ["test-market"]
    sample, sample_ui = skill("test-skill")
    original_skill = sample.read_bytes()
    result = manage("preview")
    assert result["filesWithDescriptions"] >= 3 and not requests
    assert not sample_ui.exists()
    print(ps("enable.ps1","-Start","-Python",sys.executable),flush=True)
    started = True
    until = time.monotonic()+32
    while time.monotonic()<until and not sample_ui.is_file():
        time.sleep(.4)
    assert sample_ui.is_file(), manage("status")
    assert "帮你安排课程" in sample_ui.read_text(encoding="utf-8"), sample_ui.read_bytes()
    assert "帮你安排课程" in fixture_manifest.read_text(encoding="utf-8")
    assert "帮你安排课程" in fixture_catalog.read_text(encoding="utf-8")
    display = catalog_display(codex)
    assert "帮你安排课程" in display["shortDescription"]
    assert "帮你安排课程" in display["longDescription"]
    newer, newer_ui = skill("new-skill")
    updated = json.loads(fixture_manifest.read_bytes())
    updated["interface"]["longDescription"] = "Manage an updated curriculum."
    fixture_manifest.write_text(json.dumps(updated,ensure_ascii=False),encoding="utf-8")
    until = time.monotonic()+30
    while time.monotonic()<until and (not newer_ui.is_file() or not any("updated curriculum" in row["source"] for row in requests)):
        time.sleep(.4)
    assert newer_ui.is_file()
    assert any("updated curriculum" in x["source"] for x in requests)
    assert sample.read_bytes()==original_skill
    print(ps("disable.ps1"),flush=True)
    started=False
    assert not sample_ui.exists() and not newer_ui.exists()
    assert fixture_catalog.read_bytes()==original_market
    restored = json.loads(fixture_manifest.read_bytes())
    assert restored["interface"]["shortDescription"] == json.loads(original_manifest)["interface"]["shortDescription"]
    assert restored["interface"]["longDescription"] == "Manage an updated curriculum."
    plugins=json.loads(invoke([codex,"plugin","list","--json"]))
    assert not any(p["pluginId"]=="description-zh@personal-zh-tools" for p in plugins["installed"])
    print("PASS isolated fresh install, opt-in, preview, background detection, translation, restore and uninstall",flush=True)
finally:
    if started:
        try: ps("manage.ps1","stop")
        except Exception: pass
    server.shutdown()
    server.server_close()
    workspace.cleanup()
