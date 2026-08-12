"""Web 服务层：FastAPI 对外 API + SSE 流式（选型 D5）。

职责边界：HTTP 传输层——把请求转成 TracingService 调用，不承载推理逻辑。
端点：POST /start（事故报告进，跑 7 步链）· GET /events · GET /chains/{id}
     · POST /confirm（人确认动作）· GET /stream/{id}（聊天窗 SSE 流式输出推理过程）。
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .tracing import TracingService, to_dict


def create_app(service: TracingService, nlu) -> FastAPI:
    """组装 FastAPI 应用。service/nlu 由调用方注入（二楼替换知识即可）。"""
    app = FastAPI(title="GOAI 分层溯源 Agent", version="0.1.0")

    @app.post("/start")
    def start(raw: dict[str, Any]) -> dict:
        try:
            event = nlu.parse(raw)
        except (TypeError, ValueError, KeyError) as e:
            raise HTTPException(status_code=422, detail=f"事故报告解析失败: {e}") from e
        chain = service.start(event)
        return to_dict(chain)

    @app.get("/events")
    def list_events() -> list[dict]:
        return [to_dict(e) for e in service.list_events()]

    @app.get("/chains/{chain_id}")
    def get_chain(chain_id: str) -> dict:
        try:
            return to_dict(service.get_chain(chain_id))
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/confirm")
    def confirm(payload: dict[str, Any]) -> dict:
        chain_id = payload.get("chain_id", "")
        action_ids = payload.get("action_ids", [])
        try:
            report = service.confirm(chain_id, action_ids)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return to_dict(report)

    @app.get("/stream/{chain_id}")
    def stream(chain_id: str) -> StreamingResponse:
        """SSE：逐条推送推理链的人话解释（左栏聊天窗流式输出）。"""
        try:
            chain = service.get_chain(chain_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        def gen():
            for text in chain.narrative:
                payload = json.dumps({"type": "narrative", "text": text}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                time.sleep(0.05)
            payload = json.dumps(
                {"type": "done", "status": chain.status, "root_hash": chain.root_hash},
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
