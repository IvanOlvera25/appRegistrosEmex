"""
Utilidades de fecha/hora locales.

La app corre en servidores en UTC (PythonAnywhere), pero la operación es en
Ciudad de México. Estos helpers devuelven la fecha/hora LOCAL para que
"hoy" y "mañana" correspondan a la hora de México y no se corran un día.

- Preferimos la zona horaria real (America/Mexico_City), que maneja cualquier
  cambio futuro de reglas.
- Si el sistema no tiene base de zonas, caemos a un offset fijo (CDMX = UTC-6,
  sin horario de verano desde 2022).

Configurable con APP_TIMEZONE y APP_TZ_OFFSET_HOURS.
"""
import os
from datetime import datetime, timezone, timedelta

_TZ_NAME = os.getenv("APP_TIMEZONE", "America/Mexico_City")
try:
    _FIXED_OFFSET_HOURS = float(os.getenv("APP_TZ_OFFSET_HOURS", "-6"))
except (TypeError, ValueError):
    _FIXED_OFFSET_HOURS = -6.0

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(_TZ_NAME)
except Exception:  # pragma: no cover - fallback sin base de zonas
    _TZ = timezone(timedelta(hours=_FIXED_OFFSET_HOURS))


def now_local():
    """Datetime actual en hora local (aware)."""
    return datetime.now(_TZ)


def today_local():
    """Fecha de hoy en hora local (date)."""
    return now_local().date()
