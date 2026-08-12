"""服务层 API：事故报告进 → 推理链出 → 人确认执行 → SSE 流式（端到端）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import NluSide, create_app


def _client(service):
    return TestClient(create_app(service, NluSide()))


_RAW_EVENT = {
    "entity_ref": "P1",
    "entity_type": "product",
    "ts": 100.0,
    "failed_indicators": ["surface_roughness"],
}


def test_start_returns_full_chain(service):
    client = _client(service)
    resp = client.post("/start", json=_RAW_EVENT)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "READY"
    assert data["narrative"]
    assert data["root_hash"]
    assert any(s["layer"] == "L4" for s in data["steps"])


def test_start_rejects_malformed_event(service):
    client = _client(service)
    resp = client.post("/start", json={})  # 缺 entity_ref / ts
    assert resp.status_code == 422


def test_list_events(service):
    client = _client(service)
    client.post("/start", json=_RAW_EVENT)
    resp = client.get("/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_confirm_executes_actions(service):
    client = _client(service)
    data = client.post("/start", json=_RAW_EVENT).json()
    action_ids = [a["id"] for a in data["actions"]]
    resp = client.post("/confirm", json={"chain_id": data["id"], "action_ids": action_ids})
    assert resp.status_code == 200
    report = resp.json()
    assert report["applied"], "已确认动作应全部执行落库"
    assert report["failed"] == []


def test_confirm_unknown_action_conflicts(service):
    client = _client(service)
    data = client.post("/start", json=_RAW_EVENT).json()
    resp = client.post("/confirm", json={"chain_id": data["id"], "action_ids": ["nope"]})
    assert resp.status_code == 409


def test_stream_pushes_narrative_sse(service):
    client = _client(service)
    data = client.post("/start", json=_RAW_EVENT).json()
    resp = client.get(f"/stream/{data['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "data:" in resp.text
    assert "narrative" in resp.text and "done" in resp.text


def test_chain_not_found(service):
    client = _client(service)
    assert client.get("/chains/not-exist").status_code == 404
    assert client.get("/stream/not-exist").status_code == 404
