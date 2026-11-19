"""Create exactly one agrarian Workflow app and sync only its unpublished draft.

Console writes only. PostgreSQL calls are explicit read-only identity checks.
"""

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAPH = HERE / "workflow_graph.json"
IDENTITY = HERE / "app_identity.json"
SECRET_DIR = Path("/root/mwtabel-private/agrarian-dify-20261114")
BASE = "http://127.0.0.1:8088/console/api"
NAME = "Аграрный — месячные отчёты"
TENANT = "08879bb4-93b4-4a7a-a8c5-a3f1c5306758"


def stop(message):
    raise SystemExit("STOP: " + message)


def read_secret(name):
    path = SECRET_DIR / name
    if not path.is_file() or path.stat().st_mode & 0o077:
        stop(f"private mode-0600 credential missing: {name}")
    value = path.read_text().strip()
    if not value:
        stop(f"empty credential: {name}")
    return value


def request(path, method, token, csrf, payload=None):
    headers = {
        "Authorization": "Bearer " + token,
        "X-CSRF-Token": csrf,
        "Cookie": "csrf_token=" + csrf,
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None
    except urllib.error.URLError:
        stop("Dify console is unreachable")


def db_rows():
    sql = ("SELECT id,name,tenant_id,mode,coalesce(workflow_id::text,'') FROM apps "
           "WHERE tenant_id='" + TENANT + "' AND name='" + NAME + "' ORDER BY id")
    result = subprocess.run(
        ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
         "docker-db_postgres-1", "psql", "-U", "postgres", "-d", "dify", "-X", "-q", "-A", "-t", "-F", "|", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return [line.split("|") for line in result.stdout.splitlines() if line.strip()]


def save_identity(value):
    path = IDENTITY.with_suffix(".json.tmp")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.replace(IDENTITY)


def functional(graph):
    return {
        "nodes": {node["id"]: {"type": node["data"]["type"], "code": node["data"].get("code"),
            "variables": node["data"].get("variables"), "outputs": node["data"].get("outputs"),
            "url": node["data"].get("url"), "retry": node["data"].get("retry_config"),
            "error_strategy": node["data"].get("error_strategy")}
            for node in graph["nodes"]},
        "edges": sorted((edge["source"], edge["target"]) for edge in graph["edges"]),
    }


def env_vars():
    result = []
    for name, kind, value in (
        ("AGRARIAN_SEND_ENABLED", "string", "false"),
        ("META_WHATSAPP_ACCESS_TOKEN", "secret", ""),
        ("BACKEND_REPORT_CALLBACK_TOKEN", "secret", ""),
        ("META_MESSAGES_URL", "string", ""),
        ("BACKEND_REPORT_URL", "string", ""),
    ):
        result.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "mwtabel-agrarian:" + name)),
                       "name": name, "description": name, "value_type": kind, "value": value,
                       "selector": ["env", name]})
    return result


def main():
    desired = json.loads(GRAPH.read_text())
    digest = hashlib.sha256(GRAPH.read_bytes()).hexdigest()
    token = read_secret("console-session.private")
    csrf = read_secret("console-csrf.private")
    # A fresh authenticated GET must succeed before any write.
    code, _ = request("/apps/46741506-cdaa-456b-8e04-1c5c5c3a0e7a", "GET", token, csrf)
    if code != 200:
        stop(f"console authentication failed before write: HTTP {code}")
    rows = db_rows()
    if len(rows) > 1:
        stop("multiple apps with exact name exist; no write")
    identity = json.loads(IDENTITY.read_text()) if IDENTITY.exists() else None
    if identity:
        if identity.get("name") != NAME or identity.get("tenant_id") != TENANT:
            stop("identity manifest mismatch")
        if rows and rows[0][0] != identity.get("app_id"):
            stop("manifest app ID differs from workspace app")
        if not rows:
            stop("manifest app ID missing from workspace")
    elif rows:
        stop("exact-name app exists without identity manifest; inspect before adopting")
    else:
        code, created = request("/apps", "POST", token, csrf, {
            "name": NAME, "description": "MWTabel · agrarian monthly parent reports; draft only; sending disabled", "mode": "workflow"})
        if code != 201 or not isinstance(created, dict) or not created.get("id"):
            stop(f"create app failed: HTTP {code}; response withheld")
        identity = {"name": NAME, "tenant_id": TENANT, "app_id": created["id"], "draft_id": None,
                    "desired_graph_sha256": digest, "published": False}
        save_identity(identity)  # Persist immediately so reruns cannot create another app.
        rows = db_rows()
        if len(rows) != 1 or rows[0][0] != identity["app_id"]:
            stop("new app identity or tenant mismatch after create")
        print("created app_id=" + identity["app_id"])
    if rows[0][2] != TENANT or rows[0][3] != "workflow" or rows[0][4]:
        stop("app tenant, mode or unpublished state changed")
    app_id = identity["app_id"]
    path = "/apps/" + app_id + "/workflows/draft"
    code, before = request(path, "GET", token, csrf)
    if code not in (200, 404):
        stop(f"draft GET failed: HTTP {code}")
    if code == 200 and identity.get("draft_id") and before.get("id") != identity["draft_id"]:
        stop("draft ID changed")
    if code == 200 and functional(before["graph"]) == functional(desired):
        after = before
        print("draft already matches desired graph")
    else:
        if code == 200 and identity.get("draft_id"):
            stop("existing draft graph drifted; no automatic overwrite")
        payload = {"graph": desired, "features": before["features"] if code == 200 else {},
                   "hash": before.get("hash") if code == 200 else None,
                   "environment_variables": env_vars(), "conversation_variables": []}
        status, result = request(path, "POST", token, csrf, payload)
        if status != 200 or not isinstance(result, dict) or result.get("result") != "success":
            stop(f"draft sync failed: HTTP {status}; response withheld")
        status, after = request(path, "GET", token, csrf)
        if status != 200:
            stop(f"draft reread failed: HTTP {status}")
    if after.get("version") != "draft" or functional(after["graph"]) != functional(desired):
        stop("reread draft does not functionally match prepared graph")
    actual_env = {item["name"]: item for item in after.get("environment_variables", [])}
    if set(actual_env) != {item["name"] for item in env_vars()} or actual_env["AGRARIAN_SEND_ENABLED"].get("value") != "false":
        stop("reread draft environment or false gate mismatch")
    if rows[0][4]:
        stop("app unexpectedly published")
    identity.update({"draft_id": after["id"], "desired_graph_sha256": digest, "published": False})
    save_identity(identity)
    print("verified app_id=" + app_id + " draft_id=" + after["id"] + " nodes=" + str(len(after["graph"]["nodes"])) + " edges=" + str(len(after["graph"]["edges"])))


if __name__ == "__main__":
    main()
