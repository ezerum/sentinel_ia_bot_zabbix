from __future__ import annotations
import hashlib
import logging
import time
import requests
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("bot.llm")

@dataclass
class CacheEntry:
    value: str
    expires_at: int

class TTLCache:
    def __init__(self, ttl_s: int):
        self.ttl_s = ttl_s
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> str | None:
        e = self._store.get(key)
        if not e:
            return None
        if int(time.time()) >= e.expires_at:
            self._store.pop(key, None)
            return None
        return e.value

    def set(self, key: str, value: str) -> None:
        self._store[key] = CacheEntry(value=value, expires_at=int(time.time()) + self.ttl_s)

class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[int, list[int]] = {}

    def allow(self, chat_id: int) -> bool:
        now = int(time.time())
        window_start = now - 60
        arr = self._hits.get(chat_id, [])
        arr = [t for t in arr if t >= window_start]
        if len(arr) >= self.per_minute:
            self._hits[chat_id] = arr
            return False
        arr.append(now)
        self._hits[chat_id] = arr
        return True

# -------- IA crítica (determinística) --------

def critical_classify(name: str) -> str:
    s = name.lower()
    if "offline" in s or "unreachable" in s or "down" in s:
        return "Infraestructura"
    if "cpu" in s or "memory" in s or "disk" in s:
        return "Performance"
    if "database" in s or "postgres" in s or "mysql" in s:
        return "BaseDeDatos"
    if "scanner" in s or "printer" in s or "cashdrawer" in s or "jpos" in s:
        return "Dispositivo"
    return "General"

# -------- IA conversacional (LLM) --------

class LLMEngine:
    def __init__(
        self,
        enabled: bool,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_s: int,
        max_output_tokens: int,
        max_chars: int,
        cache_ttl_s: int,
        rate_limit_per_min: int,
    ):
        self.enabled = enabled
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        self.max_chars = max_chars
        self.cache = TTLCache(cache_ttl_s)
        self.ratelimit = RateLimiter(rate_limit_per_min)

    def _key(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def analyze_incidents(self, chat_id: int, incidents_text: str) -> str:
        """
        LLM: explicación y recomendaciones.
        Se usa SOLO en /analysis y /report (no en paths críticos).
        """
        if not self.enabled:
            return "LLM deshabilitado (LLM_ENABLED=0)."

        if not self.ratelimit.allow(chat_id):
            return "Rate limit activo. Probá nuevamente en ~1 minuto."

        trimmed = incidents_text[: self.max_chars]
        prompt = (
            "Eres un analista SRE experto en Zabbix.\n"
            "Analiza los incidentes y responde en Markdown.\n"
            "Incluye:\n"
            "1) Resumen (3 bullets)\n"
            "2) Posibles causas\n"
            "3) Acciones recomendadas (paso a paso)\n"
            "4) Clasificación por categoría (Infraestructura/Performance/Aplicación/BaseDeDatos/Dispositivo/General)\n\n"
            f"INCIDENTES:\n{trimmed}\n"
        )

        k = self._key(prompt)
        cached = self.cache.get(k)
        if cached:
            return cached

        out = self._call_llm(prompt)
        self.cache.set(k, out)
        return out

    def answer_question(self, chat_id: int, question: str, context_text: str) -> str:
        """
        LLM: Q&A libre (/ask).
        """
        if not self.enabled:
            return "LLM deshabilitado (LLM_ENABLED=0)."

        if not self.ratelimit.allow(chat_id):
            return "Rate limit activo. Probá nuevamente en ~1 minuto."

        q = question[: self.max_chars]
        ctx = context_text[: self.max_chars]

        prompt = (
            "Eres un asistente de monitoreo conectado a Zabbix.\n"
            "Responde en Markdown, conciso y accionable.\n"
            "Si falta información, indica qué dato específico falta.\n\n"
            f"CONTEXTO ZABBIX:\n{ctx}\n\n"
            f"PREGUNTA:\n{q}\n"
        )

        k = self._key(prompt)
        cached = self.cache.get(k)
        if cached:
            return cached

        out = self._call_llm(prompt)
        self.cache.set(k, out)
        return out

    def _call_llm(self, prompt: str) -> str:
        # OpenAI-compatible schema. Many providers support this format.
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": self.max_output_tokens,
        }

        try:
            r = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            # OpenAI-style response
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log.exception("LLM call failed")
            return f"⚠️ Error LLM: {e}"
