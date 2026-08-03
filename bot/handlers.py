from __future__ import annotations
import logging
import time
import os
from telegram import Update
from telegram.ext import ContextTypes

from .interaction_log import InteractionLogger, InteractionEvent, now_ts
from .zabbix_client import ZabbixClient, severity_text, availability_text, enabled_text
from .llm_engine import LLMEngine, critical_classify
from .ops_client import OpsClient

log = logging.getLogger("bot.handlers")


def is_allowed(update: Update, allowed_chat_ids: set[int]) -> bool:
    if not allowed_chat_ids:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in allowed_chat_ids


def _user_name(update: Update) -> str | None:
    u = update.effective_user
    if not u:
        return None
    return u.username or f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id)


def _fmt_epoch(ts: str | int) -> str:
    try:
        t = int(ts)
        age = int(time.time()) - t
        if age < 60:
            return f"{age}s"
        if age < 3600:
            return f"{age//60}m"
        if age < 86400:
            return f"{age//3600}h"
        return f"{age//86400}d"
    except Exception:
        return str(ts)


def visual_availability(host: dict) -> tuple[str, str]:
    """
    Replica la lógica visual del frontend de Zabbix usando interfaces.
    Retorna: (texto, icono)
    """
    status = str(host.get("status", "0")).strip()
    if status == "1":
        return "Disabled", "⛔"

    interfaces = host.get("interfaces", []) or []

    iface_states = []
    for iface in interfaces:
        val = str(iface.get("available", "0")).strip()
        if val in ("0", "1", "2"):
            iface_states.append(val)

    # Fallback a campos agregados si no hay interfaces útiles
    if not iface_states:
        for key in ("available", "snmp_available", "ipmi_available"):
            val = str(host.get(key, "0")).strip()
            if val in ("0", "1", "2"):
                iface_states.append(val)

    if "2" in iface_states:
        return "Unavailable", "🔴"
    if "1" in iface_states:
        return "Available", "🟢"
    return "Unknown", "🟡"


def bind_handlers(zbx: ZabbixClient, llm: LLMEngine, allowed_chat_ids: set[int], ilog: InteractionLogger):
    # ================= OPS CONFIG =================
    ops = OpsClient(
        base_url=os.getenv("OPS_API_URL", "http://sentinel-ops:9000"),
        api_key=os.getenv("OPS_API_KEY", "")
    )
    OPS_REQUIRE_CONFIRM = os.getenv("OPS_REQUIRE_CONFIRM", "1") == "1"
    OPS_CONFIRM_TTL = int(os.getenv("OPS_CONFIRM_TTL_S", "60"))

    admins = set()
    raw_admins = os.getenv("OPS_ADMIN_TELEGRAM_IDS", "").strip()
    if raw_admins:
        admins = {int(x.strip()) for x in raw_admins.split(",") if x.strip()}

    # user_id -> (host, expires_at)
    pending_restarts: dict[int, tuple[str, int]] = {}

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        msg = (
            "🤖 *SentinelAI Monitoring Assistant*\n\n"
            "Comandos:\n"
            "/dashboard — Resumen general\n"
            "/alerts — Alertas activas recientes\n"
            "/hosts — Listar hosts\n"
            "/check <host> — Estado detallado de un host\n"
            "/services — Estado de servicios críticos\n"
            "/ack <eventid> — Reconocer alerta\n"
            "/analysis — Análisis inteligente\n"
            "/report — Reporte diario\n"
            "/ask <pregunta> — Consulta libre\n"
            "/restart <host> — Reinicio (requiere permisos)\n"
            "/help — Ayuda\n"
        )
        await update.message.reply_text(msg)#, parse_mode="Markdown")
        ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "start", update.message.text, "ok"))

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        msg = (
            "*Ayuda*\n\n"
            "Ejemplos:\n"
            "• `/alerts 60` (últimos 60m)\n"
            "• `/check XR4_LAB`\n"
            "• `/ack 192`\n"
            "• `/restart XR4_LAB`\n"
            "• `/ask por qué está offline la impresora?`\n"
        )
        await update.message.reply_text(msg)#, parse_mode="Markdown")
        ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "help", update.message.text, "ok"))

    async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        try:
            data = zbx.dashboard()
            hosts = data["hosts"]
            problems = data["problems"]
            total = len(hosts)

            disabled_count = sum(
                1 for h in hosts
                if str(h.get("status", "0")).strip() == "1"
            )

            available_count = 0
            unavailable_count = 0
            unknown_count = 0

            for h in hosts:
                av, icon = visual_availability(h)

                if av == "Disabled":
                    continue
                elif av == "Available":
                    available_count += 1
                elif av == "Unavailable":
                    unavailable_count += 1
                else:
                    unknown_count += 1

            # disabled = sum(1 for h in hosts if str(h.get("status", 0)).strip() == "1")
            # operational = total - disabled

            # hosts que tienen al menos un problema reciente
            hosts_with_alerts = len(set(
                p["hosts"][0]["hostid"] for p in problems if p.get("hosts")
            ))
            active = len(problems)
            high = sum(1 for p in problems if str(p.get("severity")) in ("4", "5"))
            
            msg = (
                f"📊 Sentinel Dashboard\n\n"
                f"Hosts totales: {total}\n"
                f"🟢 Operativos: {available_count}\n"
                f"🔴 No disponibles: {unavailable_count}\n"
                f"🟡 Unknown: {unknown_count}\n"
                f"⛔ Deshabilitados: {disabled_count}\n"
                f"⚠️ Con alertas: {hosts_with_alerts}\n\n"
                f"🚨 Problemas activos: {active}\n"
                f"High/Disaster: {high}"

            )
            await update.message.reply_text(msg)#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "dashboard", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "dashboard", update.message.text, "error", str(e)))

    async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        minutes = 60
        if context.args and context.args[0].isdigit():
            minutes = int(context.args[0])

        try:
            problems = zbx.problems_open(minutes=minutes, limit=10)
            if not problems:
                await update.message.reply_text(f"✅ Sin alertas recientes (últimos {minutes}m).")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "alerts", update.message.text, "ok"))
                return

            lines = [f"🚨 *Alertas recientes* (últimos {minutes}m):"]
            for p in problems:
                sev = severity_text(p.get("severity", "?"))
                cat = critical_classify(p.get("name", ""))
                age = _fmt_epoch(p.get("clock", "0"))
                lines.append(f"• `{p['eventid']}` — {p['name']} _(sev: {sev}, cat: {cat}, age: {age})_")
            await update.message.reply_text("\n".join(lines))#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "alerts", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "alerts", update.message.text, "error", str(e)))

    async def cmd_hosts(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        try:
            hosts = zbx.list_hosts(limit=100)
            if not hosts:
                await update.message.reply_text("No hay hosts.")
                return
            hosts = hosts[:40]
            lines = ["🖥 *Hosts (top 40)*:"]
            for h in hosts:
                # av = availability_text(h.get("available", "0"))
                # st = enabled_text(h.get("status", "0"))
                # icon = "🟢" if av == "Available" else ("🔴" if av == "Unavailable" else "🟡")
                av, icon = visual_availability(h)
                status_code = str(h.get("status", "0")).strip()
                st = "Disabled" if status_code == "1" else "Enabled"

                if status_code == "1":
                    problem_count = 0
                else:
                    problem_count = zbx.host_problem_count(h["hostid"])

                lines.append(f"• {icon} `{h['host']}` — {av} / {st} ({problem_count} alerts)")

            await update.message.reply_text("\n".join(lines))#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "hosts", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "hosts", update.message.text, "error", str(e)))

    async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        if not context.args:
            await update.message.reply_text("Uso: /check <host>\nEj: /check XR4_LAB")
            return

        query = " ".join(context.args).strip()

        try:
            matches = zbx.search_hosts(query, limit=5)
            if not matches:
                await update.message.reply_text(f"No se encontraron hosts para: {query}")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "check", update.message.text, "ok"))
                return

            if len(matches) > 1:
                msg = (
                    f"🔎 Varios hosts para '{query}':\n"
                    + "\n".join([f"• `{h['host']}`" for h in matches])
                    + "\n\nEspecifica el nombre exacto."
                )
                await update.message.reply_text(msg)#, parse_mode="Markdown")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "check", update.message.text, "ok", "multiple_matches"))
                return

            host = matches[0]
            problems = zbx.host_problems(host["hostid"], limit=10)
            av, icon = visual_availability(host)

            status_code = str(host.get("status", "0")).strip()
            status = "Disabled" if status_code == "1" else "Enabled"

            msg = (
                f"🖥 *{host['host']}*\n"
                f"Disponibilidad: *{av}*\n"
                f"Estado: *{status}*\n\n"
            )

            if problems:
                msg += "🚨 *Problemas activos:*\n"
                for p in problems:
                    sev = severity_text(p.get("severity", "?"))
                    age = _fmt_epoch(p.get("clock", "0"))
                    cat = critical_classify(p.get("name", ""))
                    msg += f"• `{p['eventid']}` — {p['name']} _(sev: {sev}, cat: {cat}, age: {age})_\n"
            else:
                msg += "✅ Sin problemas activos."

            await update.message.reply_text(msg)#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "check", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "check", update.message.text, "error", str(e)))

    async def cmd_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        try:
            services = zbx.services_status(limit=50)
            if not services:
                await update.message.reply_text("No hay servicios configurados.")
                return
            lines = ["🧩 *Servicios críticos*:"]
            for s in services[:30]:
                st = str(s.get("status", "0"))
                icon = "🟢" if st == "0" else "🔴"
                lines.append(f"• {icon} {s.get('name','(no-name)')} (status {st})")
            await update.message.reply_text("\n".join(lines))#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "services", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error services: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "services", update.message.text, "error", str(e)))

    async def cmd_ack(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        if not context.args:
            await update.message.reply_text("Uso: /ack <eventid>\nEj: /ack 192")
            return

        eventid = context.args[0].strip()
        note = "Acknowledged via Telegram SentinelAI"

        try:
            zbx.acknowledge(eventid, note)
            await update.message.reply_text(f"✅ Acknowledge enviado para eventid `{eventid}`.")#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "ack", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error ack: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "ack", update.message.text, "error", str(e)))

    async def cmd_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        chat_id = update.effective_chat.id
        try:
            problems = zbx.problems_open(minutes=120, limit=10)
            if not problems:
                await update.message.reply_text("✅ No hay incidentes recientes para analizar.")
                return

            incidents = "\n".join([f"- [{p['eventid']}] {p['name']} (sev {p['severity']})" for p in problems])
            analysis = llm.analyze_incidents(chat_id, incidents)
            await update.message.reply_text(f"🧠 *Análisis IA*\n\n{analysis}")#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), chat_id, _user_name(update), "analysis", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error analysis: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "analysis", update.message.text, "error", str(e)))

    async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        chat_id = update.effective_chat.id
        try:
            problems = zbx.problems_open(minutes=24*60, limit=30)
            if not problems:
                await update.message.reply_text("✅ No hay incidentes en las últimas 24h.")
                return

            incidents = "\n".join([f"- [{p['eventid']}] {p['name']} (sev {p['severity']})" for p in problems])
            analysis = llm.analyze_incidents(chat_id, incidents)
            await update.message.reply_text(f"🗓 *Reporte 24h*\n\n{analysis}")#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), chat_id, _user_name(update), "report", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error report: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "report", update.message.text, "error", str(e)))

    async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return
        chat_id = update.effective_chat.id
        question = " ".join(context.args).strip()
        if not question:
            await update.message.reply_text("Uso: /ask <pregunta>\nEj: /ask por qué está offline la impresora?")
            return

        try:
            problems = zbx.problems_open(minutes=180, limit=10)
            ctx = "\n".join([f"- [{p['eventid']}] {p['name']} sev={p['severity']}" for p in problems]) if problems else "(sin problemas recientes)"
            answer = llm.answer_question(chat_id, question, ctx)
            await update.message.reply_text(answer)#, parse_mode="Markdown")
            ilog.write(InteractionEvent(now_ts(), chat_id, _user_name(update), "ask", update.message.text, "ok"))
        except Exception as e:
            await update.message.reply_text(f"Error ask: {e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "ask", update.message.text, "error", str(e)))

    # ================= /restart =================
    async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return

        user_id = update.effective_user.id
        if admins and user_id not in admins:
            await update.message.reply_text("❌ No autorizado para ejecutar reinicios.")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart", update.message.text, "denied", "not_admin"))
            return

        if not context.args:
            await update.message.reply_text("Uso: /restart <host>\nEj: /restart REG004")
            return

        host = context.args[0].strip()

        if OPS_REQUIRE_CONFIRM:
            pending_restarts[user_id] = (host, int(time.time()) + OPS_CONFIRM_TTL)
            await update.message.reply_text(
                f"⚠️ Confirmación requerida.\n"
                f"Para reiniciar `{host}` respondé:\n"
                f"`CONFIRM RESTART {host}`\n"
                f"(válido {OPS_CONFIRM_TTL}s)",
                parse_mode="Markdown"
            )
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart", update.message.text, "pending", f"host={host}"))
            return

        actor = _user_name(update) or str(user_id)
        try:
            result = ops.call_action("restart_host", host, actor, "Requested via Telegram")
            await update.message.reply_text(f"✅ Reinicio solicitado.\nrequest_id={result.get('request_id')}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart", update.message.text, "ok", f"request_id={result.get('request_id')}"))
        except Exception as e:
            await update.message.reply_text(f"❌ Error ejecutando acción:\n{e}")
            ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart", update.message.text, "error", str(e)))

    # fallback libre + confirmación
    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_allowed(update, allowed_chat_ids):
            return

        user_id = update.effective_user.id
        text = (update.message.text or "").strip()

        # CONFIRM RESTART <HOST>
        if text.upper().startswith("CONFIRM RESTART "):
            host = text.split(" ", 2)[2].strip()
            pending = pending_restarts.get(user_id)

            if not pending:
                await update.message.reply_text("No hay reinicio pendiente. Usá /restart <host>.")
                return

            pending_host, expires_at = pending

            if int(time.time()) > expires_at:
                pending_restarts.pop(user_id, None)
                await update.message.reply_text("⏳ Confirmación expirada. Reintentá /restart <host>.")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart_confirm", update.message.text, "expired"))
                return

            if host != pending_host:
                await update.message.reply_text(f"Host no coincide. Pendiente: {pending_host}")
                return

            if admins and user_id not in admins:
                await update.message.reply_text("❌ No autorizado para confirmar reinicios.")
                pending_restarts.pop(user_id, None)
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart_confirm", update.message.text, "denied", "not_admin"))
                return

            actor = _user_name(update) or str(user_id)
            try:
                result = ops.call_action("restart_host", host, actor, "Confirmed via Telegram")
                pending_restarts.pop(user_id, None)
                await update.message.reply_text(f"✅ Reinicio solicitado.\nrequest_id={result.get('request_id')}")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart_confirm", update.message.text, "ok", f"request_id={result.get('request_id')}"))
            except Exception as e:
                await update.message.reply_text(f"❌ Error ejecutando acción:\n{e}")
                ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "restart_confirm", update.message.text, "error", str(e)))
            return

        await update.message.reply_text("Usá /help para ver comandos. Sugerencia: /alerts, /check <host>, /ack <eventid>, /restart <host>.")
        ilog.write(InteractionEvent(now_ts(), update.effective_chat.id, _user_name(update), "text", update.message.text, "ok"))

    return {
        "start": cmd_start,
        "help": cmd_help,
        "dashboard": cmd_dashboard,
        "alerts": cmd_alerts,
        "hosts": cmd_hosts,
        "check": cmd_check,
        "services": cmd_services,
        "ack": cmd_ack,
        "analysis": cmd_analysis,
        "report": cmd_report,
        "ask": cmd_ask,
        "restart": cmd_restart,
        "on_text": on_text,
    }
