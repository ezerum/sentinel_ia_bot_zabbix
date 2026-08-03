from __future__ import annotations
import os
import time
import json
import hmac
import hashlib
import requests


class OpsClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _sign(self, body: bytes, ts: str) -> str:
        """
        Firma HMAC: HMAC(secret, timestamp.body)
        """
        msg = ts.encode() + b"." + body
        return hmac.new(self.api_key.encode(), msg, hashlib.sha256).hexdigest()

    def call_action(self, action: str, host: str, actor: str, reason: str | None = None):
        """
        Envía acción al Orchestrator.
        """
        payload = {
            "action": action,
            "host": host,
            "actor": actor,
            "reason": reason,
        }

        body = json.dumps(payload).encode("utf-8")
        ts = str(int(time.time()))
        sig = self._sign(body, ts)

        r = requests.post(
            f"{self.base_url}/v1/actions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Timestamp": ts,
                "X-Signature": sig,
            },
            timeout=self.timeout_s,
        )

        if r.status_code >= 400:
            raise RuntimeError(f"OPS error {r.status_code}: {r.text}")

        return r.json()
