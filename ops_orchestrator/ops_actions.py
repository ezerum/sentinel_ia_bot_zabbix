from __future__ import annotations
from dataclasses import dataclass
from zabbix_client import ZabbixClient


@dataclass
class ExecResult:
    ok: bool
    output: str


def restart_host(zbx: ZabbixClient, host: str, script_name: str = "Restart host") -> ExecResult:
    try:
        # Obtener hostid
        hostid = zbx.get_hostid_by_host(host)
        if not hostid:
            return ExecResult(False, "Host not found in Zabbix")

        # Obtener scriptid
        scripts = zbx.call("script.get", {
            "output": ["scriptid", "name"],
            "filter": {"name": [script_name]}
        })

        if not scripts:
            return ExecResult(False, "Restart script not found")

        scriptid = scripts[0]["scriptid"]

        # Ejecutar script
        zbx.call("script.execute", {
            "scriptid": scriptid,
            "hostid": hostid
        })

        return ExecResult(True, "Restart command sent via Zabbix agent")

    except Exception as e:
        return ExecResult(False, str(e))
