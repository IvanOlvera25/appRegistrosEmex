"""
Consulta de planeación vía WhatsApp.

Permite responder preguntas tipo "¿cuál es la planeación de Juan para mañana?"
o "¿qué tengo mañana?" leyendo lo registrado en la plataforma (DailyPlan).

Reglas de autorización:
- Un número registrado como admin puede consultar la planeación de cualquiera.
- Un trabajador solo puede consultar la suya.
- Un número no registrado no recibe datos.
"""
import os
import re
import json
import unicodedata
from datetime import date, datetime, timedelta

from ..extensions import db
from ..models import DailyPlan, User
from ..timeutils import today_local

try:
    from openai import OpenAI
    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:  # pragma: no cover
    _client = None


# Palabras que delatan una consulta de planeación (ya sin acentos)
_PLAN_KEYWORDS = ("planeacion", "planeación", "planificacion", "planificación",
                  "que tengo", "que hago", "que voy a hacer", "mi plan", "que debo hacer")


def _strip_accents(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def is_plan_query(text: str) -> bool:
    """Detecta si el mensaje es una consulta de planeación (no un registro)."""
    t = _strip_accents(text).strip()
    if not t:
        return False
    return any(kw in t for kw in _PLAN_KEYWORDS)


# =============================================================
# Extracción de {persona, fecha} desde el texto
# =============================================================
_EXTRACT_PROMPT = (
    "Extrae de la pregunta a QUÉ persona y para QUÉ fecha se consulta su planeación de trabajo. "
    "Responde SOLO un JSON: {\"persona\": <nombre o 'yo'>, \"fecha\": <'hoy'|'mañana'|'YYYY-MM-DD'>}. "
    "Si no menciona persona o dice 'mi/yo/tengo', usa 'yo'. Si no menciona fecha, usa 'mañana'."
)


def _extract_with_ai(text: str):
    if not _client:
        return None
    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Aísla el JSON aunque venga con texto alrededor
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group())
    except Exception as e:
        print(f"[plan_service] Falló extracción IA: {e}")
        return None


def _extract_fallback(text: str):
    """Extracción simple sin IA (respaldo)."""
    t = _strip_accents(text)
    fecha = "manana"
    if "hoy" in t:
        fecha = "hoy"
    # Persona: texto después de "de " o "para " (excluyendo 'mañana/hoy')
    persona = "yo"
    m = re.search(r"\b(?:de|para)\s+([a-záéíóúñ ]{2,40})", text, re.IGNORECASE)
    if m:
        cand = m.group(1).strip()
        cand = re.sub(r"\b(ma[ñn]ana|hoy|para|el|la)\b", "", cand, flags=re.IGNORECASE).strip()
        if cand:
            persona = cand
    return {"persona": persona, "fecha": "mañana" if fecha == "manana" else "hoy"}


def _resolve_date(value) -> date:
    today = today_local()
    if not value:
        return today + timedelta(days=1)
    v = _strip_accents(str(value)).strip()
    if v == "hoy":
        return today
    if v in ("manana", "mañana"):
        return today + timedelta(days=1)
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except Exception:
        return today + timedelta(days=1)


def _resolve_worker(persona, sender_user):
    """Devuelve (worker, error_msg). worker=None si no se pudo/está prohibido."""
    p = (persona or "").strip()
    is_self = (not p) or _strip_accents(p) in ("yo", "mi", "mia", "mía", "mi planeacion")

    if is_self:
        if not sender_user:
            return None, "No encuentro tu número registrado en EMEX, por eso no puedo mostrar tu planeación."
        return sender_user, None

    # Consulta sobre OTRA persona -> requiere admin
    if not sender_user or getattr(sender_user, "role", None) != "admin":
        return None, "🔒 Solo puedes consultar *tu propia* planeación. Escribe: \"¿qué tengo mañana?\""

    worker = (
        User.query
        .filter(User.name.ilike(f"%{p}%"))
        .order_by(User.name.asc())
        .first()
    )
    if not worker:
        return None, f"No encontré a un trabajador llamado \"{p}\" en el sistema."
    return worker, None


# =============================================================
# Formato de respuesta
# =============================================================
_ICON = {"cumplido": "✅", "no_cumplido": "⛔", "pendiente": "⬜"}


def _format_plan(worker, day: date):
    plans = (
        DailyPlan.query
        .filter(DailyPlan.worker_id == worker.id, DailyPlan.plan_date == day)
        .order_by(DailyPlan.id.asc())
        .all()
    )

    day_label = day.strftime("%d/%m/%Y")
    if not plans:
        return (f"📅 *{day_label}*\n👤 {worker.name}\n\n"
                f"No hay planeación registrada para esa fecha.")

    lines = [f"📅 *Planeación {day_label}*", f"👤 {worker.name}"]
    for plan in plans:
        lines.append("")
        lines.append(f"*{plan.type_label}*")
        if plan.notes:
            lines.append(f"📝 {plan.notes}")
        if not plan.items:
            lines.append("• (sin tareas)")
        for item in plan.items:
            icon = _ICON.get(item.status, "⬜")
            extra = " (extra)" if item.is_extra else ""
            detail_bits = []
            if item.unit:
                detail_bits.append(f"🔧 {item.unit.code}")
            if item.location_label:
                detail_bits.append(f"📍 {item.location_label}")
            if item.trip_type:
                detail_bits.append(f"🚛 {item.trip_type}")
            if item.quantity:
                detail_bits.append(f"🔁 {item.quantity}")
            detail = ("  " + " · ".join(detail_bits)) if detail_bits else ""
            lines.append(f"{icon} {item.description}{extra}{detail}")
            if item.status == "no_cumplido" and item.justification:
                lines.append(f"   ⚠️ {item.justification}")
    return "\n".join(lines)


def answer_plan_query(text: str, sender_user) -> str:
    """Punto de entrada: recibe el texto y el User remitente (o None)."""
    parsed = _extract_with_ai(text) or _extract_fallback(text)
    persona = parsed.get("persona") if isinstance(parsed, dict) else "yo"
    fecha = parsed.get("fecha") if isinstance(parsed, dict) else None

    worker, err = _resolve_worker(persona, sender_user)
    if err:
        return err

    day = _resolve_date(fecha)
    return _format_plan(worker, day)
