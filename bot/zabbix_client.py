from __future__ import annotations
import logging
import requests
import time
from typing import Any

log = logging.getLogger("bot.zabbix")

class ZabbixAPIError(RuntimeError):
    pass

class ZabbixClient:
    """
    Zabbix 7.4.x:
      - Content-Type: application/json-rpc
      - Authorization: Bearer <API_TOKEN>
    """
    def __init__(self, base_url: str, api_token: str, timeout_s: int = 20):
        self.endpoint = f"{base_url.rstrip('/')}/api_jsonrpc.php"
        self.api_token = api_token
        self.timeout_s = timeout_s
        self._id = 1

    def call(self, method: str, params: dict[str, Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._id,
        }
        self._id += 1

        headers = {
            "Content-Type": "application/json-rpc",
            "Authorization": f"Bearer {self.api_token}",
        }

        r = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_s)
        r.raise_for_status()

        data = r.json()
        if "error" in data:
            raise ZabbixAPIError(str(data["error"]))
        return data["result"]

    # -------- High-level methods --------

    def problems_open(self, minutes: int = 60, limit: int = 10) -> list[dict[str, Any]]:
        # Zabbix 7.4: sortfield must be "eventid"
        return self.call("problem.get", {
            "output": ["eventid", "name", "severity", "clock"],
            "recent": True,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "time_from": int(time.time()) - minutes * 60,
            "limit": limit,
        })

    # def list_hosts(self, limit: int = 200) -> list[dict[str, Any]]:
      #  return self.call("host.get", {
       #     "output": ["host", "available", "status", "snmp_available", "ipmi_available"],
        #    "limit": limit,
        #})
    
    def list_hosts(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.call("host.get", {
            "output": [
                "hostid",
                "host",
                "name",
                "status",
                "available",
                "snmp_available",
                "ipmi_available"
            ],
            "selectInterfaces": [
                "interfaceid",
                "type",
                "main",
                "useip",
                "ip",
                "dns",
                "available"
           ],
           "sortfield": "host",
           "sortorder": "ASC",
           "limit": limit,
       })


    def search_hosts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.call("host.get", {
            "output": [
                "hostid",
                "host",
                "name",
                "status",
                "available",
                "snmp_available",
                "ipmi_available"
            ],
            "search": {
                "host": query
            },
            "searchWildcardsEnabled": True,
            "selectInterfaces": [
                "interfaceid",
                "type",
                "main",
                "useip",
                "ip",
                "dns",
                "available"
            ],
            "sortfield": "host",
            "sortorder": "ASC",
            "limit": limit
        })
        

    def host_detail(self, host: str) -> dict[str, Any] | None:
        hosts = self.call("host.get", {
            "output": ["hostid", "host", "name", "available", "status"],
            "filter": {"host": [host]},
            "limit": 1,
        })
        if not hosts:
            return None
        return hosts[0]

    def host_problems(self, hostid: str, limit: int = 20, minutes: int = 60) -> list[dict[str, Any]]:
        return self.call("problem.get", {
            "output": ["eventid", "name", "severity", "clock"],
            "hostids": hostid,
            "recent": True,
            "time_from": int(time.time()) - minutes * 60,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": limit,
        })

    def host_problem_count(self, hostid: str, minutes: int = 60) -> int:
        """
        Devuelve cantidad de problemas del host en los últimos N minutos.
        """
        result = self.call("problem.get", {
            "output": ["eventid"],
            "hostids": hostid,
            "recent": True,
            "time_from": int(time.time()) - minutes * 60
        })

        return len(result)    

    def acknowledge(self, eventid: str, message: str) -> Any:
        return self.call("event.acknowledge", {
            "eventids": [eventid],
            "action": 1,
            "message": message,
        })

    def dashboard(self) -> dict[str, Any]:
        hosts = self.list_hosts(limit=500)
        problems = self.problems_open(minutes=24*60, limit=200)  # últimas 24h, ajustable
        return {"hosts": hosts, "problems": problems}

    def services_status(self, limit: int = 100) -> list[dict[str, Any]]:
        # Si no usás services, puede fallar: lo manejamos arriba en handler.
        return self.call("service.get", {
            "output": ["name", "status"],
            "limit": limit,
        })

def severity_text(sev: str | int) -> str:
    m = {
        "0": "Not classified",
        "1": "Information",
        "2": "Warning",
        "3": "Average",
        "4": "High",
        "5": "Disaster",
    }
    return m.get(str(sev), str(sev))

def availability_text(av: str | int) -> str:
    # 0 unknown, 1 available, 2 unavailable
    return {"0": "Unknown", "1": "Available", "2": "Unavailable"}.get(str(av), str(av))

def enabled_text(st: str | int) -> str:
    return "Enabled" if str(st) == "0" else "Disabled"
