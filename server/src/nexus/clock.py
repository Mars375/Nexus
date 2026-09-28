"""Horodatage unique de Nexus : ISO-8601 avec fuseau Europe/Paris (DATA-MODEL §1)."""

from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")


def now() -> datetime:
    return datetime.now(TZ)
