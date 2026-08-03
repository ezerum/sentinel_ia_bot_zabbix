from __future__ import annotations
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .config import load_settings
from .logging_setup import setup_logging
from .interaction_log import InteractionLogger
from .zabbix_client import ZabbixClient
from .llm_engine import LLMEngine
from .handlers import bind_handlers

log = logging.getLogger("bot.main")

def main() -> None:
    s = load_settings()
    setup_logging(s.log_dir, s.log_level)

    log.info("Starting SentinelAI bot (polling).")

    ilog = InteractionLogger(s.log_dir)

    zbx = ZabbixClient(
        base_url=s.zabbix_url,
        api_token=s.zabbix_api_token,
        timeout_s=20,
    )

    llm = LLMEngine(
        enabled=s.llm_enabled,
        endpoint=s.llm_endpoint,
        api_key=s.llm_api_key,
        model=s.llm_model,
        timeout_s=s.llm_timeout_s,
        max_output_tokens=s.llm_max_output_tokens,
        max_chars=s.llm_max_chars,
        cache_ttl_s=s.llm_cache_ttl_s,
        rate_limit_per_min=s.llm_rate_limit_per_min,
    )

    handlers = bind_handlers(zbx, llm, s.allowed_chat_ids, ilog)

    app = Application.builder().token(s.telegram_bot_token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", handlers["start"]))
    app.add_handler(CommandHandler("help", handlers["help"]))
    app.add_handler(CommandHandler("dashboard", handlers["dashboard"]))
    app.add_handler(CommandHandler("alerts", handlers["alerts"]))
    app.add_handler(CommandHandler("hosts", handlers["hosts"]))
    app.add_handler(CommandHandler("check", handlers["check"]))
    app.add_handler(CommandHandler("services", handlers["services"]))
    app.add_handler(CommandHandler("ack", handlers["ack"]))
    app.add_handler(CommandHandler("analysis", handlers["analysis"]))
    app.add_handler(CommandHandler("report", handlers["report"]))
    app.add_handler(CommandHandler("ask", handlers["ask"]))
    app.add_handler(CommandHandler("restart", handlers["restart"]))

    # Fallback text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers["on_text"]))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
