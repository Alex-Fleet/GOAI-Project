"""测试共享工具：离线 stub（LLM/embedding）+ 简单分词 + chunk 构造。

不碰真实网络——D6 离线验证用确定性 stub，真实客户端只在 env 配 key 后由二楼启用。
"""

from __future__ import annotations

from engine.kb.chunking import Chunk


class StubLLM:
    """可编程 LLM stub：respond 为固定字符串或 (system,user,json_mode)->str 回调。"""

    def __init__(self, respond):
        self._respond = respond
        self.calls: list[tuple[str, str, bool]] = []

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        self.calls.append((system, user, json_mode))
        if callable(self._respond):
            return self._respond(system, user, json_mode)
        return self._respond


class StubEmbedder:
    """确定性 embedding stub：字符 ord 直方图——相近文本向量相近（ord 跨 run 稳定）。"""

    DIM = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.DIM
            for ch in t:
                vec[ord(ch) % self.DIM] += 1.0
            out.append(vec)
        return out

    def dim(self) -> int:
        return self.DIM


def whitespace_tokenize(text: str) -> list[str]:
    return [t for t in text.split() if t]


def make_chunk(
    text: str, doc_id: str = "doc", kind: str = "section", cid: str | None = None
) -> Chunk:
    return Chunk(
        id=cid or f"{doc_id}:1:0",
        doc_id=doc_id,
        kind=kind,
        text=text,
        source_ref=f"{doc_id}#L1",
    )
