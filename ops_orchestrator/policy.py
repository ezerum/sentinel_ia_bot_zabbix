from __future__ import annotations
import os
import time
from dataclasses import dataclass
from zabbix_client import ZabbixClient

@dataclass
class PolicyDecision:
    ok: bool
    reason: str
    evidence: dict

def check_restart_policy(zbx: ZabbixClient, host: str) -> PolicyDecision:
    require_problem = os.getenv("OPS_REQUIRE_ACTIVE_PROBLEM", "1") == "1"
    min_sev = int(os.getenv("OPS_MIN_SEVERITY", "3"))
    lookback_min = int(os.getenv("OPS_PROBLEM_LOOKBACK_MIN", "180"))

    hostid = zbx.get_hostid_by_host(host)
    if not hostid:
        return PolicyDecision(False, "host_not_found_in_zabbix", {"host": host})

    if not require_problem:
        return PolicyDecision(True, "policy_allows_without_problem", {"host": host, "hostid": hostid})

    time_from = int(time.time()) - lookback_min * 60
    ok, problems = zbx.host_has_active_problem(hostid, time_from=time_from, min_severity=min_sev)
    if not ok:
        return PolicyDecision(
            False,
            "no_active_problem_for_host",
            {"host": host, "hostid": hostid, "min_severity": min_sev, "lookback_min": lookback_min}
        )

    return PolicyDecision(
        True,
        "active_problem_found",
        {"host": host, "hostid": hostid, "min_severity": min_sev, "problems": problems}
    )
