from __future__ import annotations
import os
import json
import uuid
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

from auth import verify
from audit import AuditLogger, AuditEvent, now
from ops_actions import restart_host
from zabbix_client import ZabbixClient
from policy import check_restart_policy

OPS_API_KEY = os.getenv("OPS_API_KEY", "")
AUDIT_PATH = os.getenv("OPS_AUDIT_PATH", "logs/ops_audit.jsonl")

ALLOWED_ACTIONS = set(x.strip() for x in os.getenv("OPS_ALLOWED_ACTIONS", "").split(",") if x.strip())

OPS_ZABBIX_URL = os.getenv("OPS_ZABBIX_URL", "")
OPS_ZABBIX_API_TOKEN = os.getenv("OPS_ZABBIX_API_TOKEN", "")

app = FastAPI(title="Sentinel Ops Orchestrator")
audit = AuditLogger(AUDIT_PATH)

zbx = None
if OPS_ZABBIX_URL and OPS_ZABBIX_API_TOKEN:
    zbx = ZabbixClient(OPS_ZABBIX_URL, OPS_ZABBIX_API_TOKEN)

class ActionRequest(BaseModel):
    action: str
    host: str
    actor: str
    reason: str | None = None

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/v1/actions")
async def actions(req: Request):
    body = await req.body()

    ts = req.headers.get("X-Timestamp", "")
    sig = req.headers.get("X-Signature", "")
    if not OPS_API_KEY or not verify(OPS_API_KEY, body, ts, sig):
        raise HTTPException(status_code=401, detail="unauthorized")

    data = json.loads(body.decode("utf-8"))
    ar = ActionRequest(**data)

    request_id = str(uuid.uuid4())

    # Policy: acción permitida
    if ALLOWED_ACTIONS and ar.action not in ALLOWED_ACTIONS:
        audit.write(AuditEvent(ts=now(), actor=ar.actor, action=ar.action, host=ar.host,
                               status="error", detail="action_not_allowed_by_policy", request_id=request_id))
        raise HTTPException(status_code=403, detail="Action not allowed by policy")

    # Acción
    if ar.action == "restart_host":
        # Policy: host debe tener problema activo
        if not zbx:
            audit.write(AuditEvent(ts=now(), actor=ar.actor, action=ar.action, host=ar.host,
                                   status="error", detail="zabbix_policy_not_configured", request_id=request_id))
            raise HTTPException(status_code=500, detail="Zabbix policy not configured")

        decision = check_restart_policy(zbx, ar.host)
        if not decision.ok:
            audit.write(AuditEvent(ts=now(), actor=ar.actor, action=ar.action, host=ar.host,
                                   status="denied", detail=decision.reason, request_id=request_id))
            raise HTTPException(status_code=409, detail=f"Denied: {decision.reason}")

        # Ejecutar reinicio
        res = restart_host(zbx, ar.host)
        audit.write(AuditEvent(
            ts=now(), actor=ar.actor, action=ar.action, host=ar.host,
            status="ok" if res.ok else "error",
            detail=(res.output if res.output else decision.reason),
            request_id=request_id
        ))

        if not res.ok:
            raise HTTPException(status_code=400, detail=res.output)

        return {"ok": True, "request_id": request_id, "policy": decision.evidence, "result": res.output}

    audit.write(AuditEvent(ts=now(), actor=ar.actor, action=ar.action, host=ar.host,
                           status="error", detail="unknown_action", request_id=request_id))
    raise HTTPException(status_code=400, detail="unknown_action")
