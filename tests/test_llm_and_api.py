import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

import pytest

from cohort import llm

REPLY = ('Sure.\n```json\n{"filter": [{"attr": "condition", "op": "has", "value": "diabete"}, '
         '{"attr": "age", "op": ">", "value": "65"}], "note": "a {brace} in a string"}\n```')


class FakeModel(BaseHTTPRequestHandler):
    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"data": [{"id": "fake-model"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._send({"choices": [{"message": {"content": REPLY}}],
                    "usage": {"prompt_tokens": 900, "completion_tokens": 40}})

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_model(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    yield
    server.shutdown()


def test_first_object_skips_prose_and_fences():
    assert llm._first_object(REPLY)["note"] == "a {brace} in a string"
    with pytest.raises(ValueError):
        llm._first_object("no json here")


def test_draft_against_a_fake_endpoint(fake_model, cat):
    out = llm.draft("diabetici over 65", cat)
    assert out["error"] is None
    assert out["model"] == "fake-model"
    assert out["tokens"] == [900, 40]
    assert len(out["filter"]) == 2


def test_draft_never_raises_when_the_endpoint_is_down(monkeypatch, cat):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.setenv("LLM_TIMEOUT", "2")
    out = llm.draft("anything", cat)
    assert out["filter"] == [] and "unreachable" in out["error"]


class Scripted(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        status, headers, payload, *delay = self.server.script.pop(0)
        time.sleep(delay[0] if delay else 0)
        body = json.dumps(payload).encode()
        try:
            self.send_response(status)
            for k, v in {"Content-Type": "application/json", **headers}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def scripted(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Scripted)
    server.script, server.seen = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.delenv("LLM_REASONING", raising=False)
    yield server
    server.shutdown()


def test_short_rate_limits_are_retried(scripted, monkeypatch, cat):
    ok = {"choices": [{"message": {"content": REPLY}}]}
    scripted.script += [(429, {"Retry-After": "0"}, {"error": {}}), (200, {}, ok)]
    monkeypatch.setenv("LLM_REASONING", "low")
    out = llm.draft("diabetici over 65", cat)
    assert out["error"] is None and len(scripted.seen) == 2
    assert scripted.seen[0]["reasoning_effort"] == "low"


def test_long_rate_limits_are_reported_not_waited(scripted, cat):
    scripted.script.append((429, {"Retry-After": "60"}, {"error": {}}))
    out = llm.draft("anything", cat)
    assert "rate limited" in out["error"] and len(scripted.seen) == 1
    assert "reasoning_effort" not in scripted.seen[0]


def test_a_stalled_request_is_sent_once_more(scripted, monkeypatch, cat):
    ok = {"choices": [{"message": {"content": REPLY}}]}
    scripted.script += [(200, {}, ok, 1.5), (200, {}, ok)]
    monkeypatch.setenv("LLM_TIMEOUT", "0.5")
    out = llm.draft("diabetici over 65", cat)
    assert out["error"] is None and len(scripted.seen) == 2


def test_reasoning_that_eats_the_budget_is_named(scripted, cat):
    scripted.script.append((200, {}, {"choices": [{"message": {"content": ""},
                                                   "finish_reason": "length"}]}))
    out = llm.draft("anything", cat)
    assert "ran out of tokens" in out["error"]


def test_prompt_lists_every_key(cat):
    from datetime import date
    prompt = llm.system_prompt(cat, date(2026, 10, 12))
    for key in list(cat.conditions) + list(cat.attrs) + list(cat.chapters) + list(cat.areas):
        assert key in prompt


@pytest.fixture
def client(small_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from cohort import api
    monkeypatch.setattr(api, "DB_PATH", small_db)
    monkeypatch.setattr(api, "LOG_PATH", str(tmp_path / "events.jsonl"))
    with TestClient(api.app) as c:
        yield c


def test_api_round_trip(client, fake_model):
    assert len(client.get("/api/catalog").json()["conditions"]) > 50
    d = client.post("/api/draft", json={"request": "diabetici over 65"}).json()
    assert d["filter"] == [{"attr": "condition", "op": "has", "value": "diabetes"},
                           {"attr": "age", "op": "gt", "value": 65}]
    assert d["runnable"]
    edited = d["filter"] + [{"attr": "sex", "op": "eq", "value": "female"}]
    r = client.post("/api/run", json={"request": "diabetici over 65", "filter": edited,
                                      "drafted": d["filter"], "draft_id": d["id"]}).json()
    assert r["edited"] is True
    assert r["result"]["count"] <= 3000
    steps = r["result"]["steps"]
    assert len(steps) == 3 and steps == sorted(steps, reverse=True)
    assert steps[-1] == r["result"]["count"]
    s = client.get("/api/stats").json()
    assert s["drafts"] == 1 and s["runs"] == 1 and s["runs_edited"] == 1


def test_api_refuses_to_run_a_blocked_filter(client):
    r = client.post("/api/run", json={"request": "long covid", "filter": []})
    assert r.status_code == 422


def test_saved_draft_is_replayed_only_when_the_model_is_down(client, monkeypatch):
    from cohort import api
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.setenv("LLM_TIMEOUT", "2")
    saved = {"request": "Patients with long COVID", "model": "m", "date": "2026-10-17",
             "filter": [{"attr": "condition", "op": "has", "value": "long_covid"}], "note": ""}
    monkeypatch.setitem(api.state, "saved", {api._key(saved["request"]): saved})
    d = client.post("/api/draft", json={"request": "patients  with long covid "}).json()
    assert d["saved"]["model"] == "m" and "unreachable" in d["saved"]["reason"]
    assert d["llm"]["error"] is None and d["filter"] == saved["filter"]
    assert any(i["level"] == "error" for i in d["issues"])
    other = client.post("/api/draft", json={"request": "diabetici over 65"}).json()
    assert other["saved"] is None and other["filter"] == []
    assert client.get("/api/stats").json()["drafts"] == 0


def test_draft_limit_per_visitor(client, fake_model, monkeypatch):
    from cohort import api
    monkeypatch.setattr(api, "DRAFT_LIMIT", 2)
    monkeypatch.setattr(api, "recent", {})
    ask = lambda ip: client.post("/api/draft", json={"request": "diabetici over 65"},
                                 headers={"X-Forwarded-For": ip}).json()
    assert ask("1.1.1.1")["llm"]["error"] is None
    assert ask("1.1.1.1")["llm"]["error"] is None
    assert "limit" in ask("1.1.1.1")["llm"]["error"]
    assert ask("2.2.2.2")["llm"]["error"] is None
