from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class InteractionEvent:
    ts: int
    chat_id: int | None
    user: str | None
    command: str | None
    text: str | None
    status: str
    note: str | None = None

class InteractionLogger:
    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, "interactions.jsonl")

    def write(self, ev: InteractionEvent) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

def now_ts() -> int:
    return int(time.time())
