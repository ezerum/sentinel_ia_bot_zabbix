from __future__ import annotations
import requests

class ZabbixAPIError(RuntimeError):
    pass

class ZabbixClient:
    def __init__(self, base_url: str, api_token: str, timeout_s: int = 20):
        self.endpoint = f"{base_url.rstrip('/')}/api_jsonrpc.php"
        self.token = api_token
        self.timeout_s = timeout_s
        self._id = 1

    def call(self, method: str, params: dict):
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id}
        self._id += 1

        headers = {
            "Content-Type": "application/json-rpc",
            "Authorization": f"Bearer {self.token}",
        }

        r = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise ZabbixAPIError(str(data["error"]))
        return data["result"]

    def get_hostid_by_host(self, host: str) -> str | None:
        res = self.call("host.get", {
            "output": ["hostid", "host"],
            "filter": {"host": [host]},
            "limit": 1
        })
        if not res:
            return None
        return res[0]["hostid"]

    def host_has_active_problem(self, hostid: str, time_from: int, min_severity: int) -> tuple[bool, list[dict]]:
        # Para política de reinicio: basta con saber si hay problemas activos.
        # Zabbix 7.4: sortfield debe ser eventid
        problems = self.call("problem.get", {
            "output": ["eventid", "name", "severity", "clock"],
            "hostids": [hostid],
            "recent": True,
            "time_from": time_from,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": 10
        })

        filtered = [p for p in problems if int(p.get("severity", 0)) >= min_severity]
        return (len(filtered) > 0), filtered
