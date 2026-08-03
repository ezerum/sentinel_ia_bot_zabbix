import json, os, time
from dataclasses import dataclass, asdict

@dataclass
class AuditEvent:
    ts: int
    actor: str
    action: str
    host: str
    status: str
    detail: str | None = None
    request_id: str | None = None

class AuditLogger:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path

    def write(self, ev: AuditEvent) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

def now() -> int:
    return int(time.time())
