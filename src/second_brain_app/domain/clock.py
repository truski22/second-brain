import re
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import dateparser


class Clock:
    def __init__(self, timezone: str = "", now: Callable[[], datetime] | None = None):
        self.timezone = timezone
        self._now = now

    def now(self) -> datetime:
        if self._now:
            return self._now()
        return datetime.now(ZoneInfo(self.timezone)) if self.timezone else datetime.now().astimezone()

    def context(self) -> dict:
        now = self.now()
        return {"date": now.date().isoformat(), "datetime": now.isoformat(),
                "timezone": self.timezone or str(now.tzinfo), "source": "operating_system"}

    def resolve(self, expression: str) -> str | None:
        text = expression.strip().lower()
        if not text:
            return None
        # Slash dates and vague periods have no unique day.
        if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d+)?\b", text) \
                and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError("Fecha ambigua. Indica día, mes y año, o YYYY-MM-DD.")
        if re.search(r"\b(week|month|soon|later|semana|mes|pronto|luego)\b", text):
            raise ValueError("Indica un día concreto para el recordatorio.")
        if re.search(r"\d\s*:\s*\d|\b(am|pm|horas?|hours?)\b", text):
            raise ValueError("Los recordatorios admiten fechas, no alarmas con hora.")
        offsets = {"hoy": 0, "today": 0, "mañana": 1, "manana": 1, "tomorrow": 1,
                   "pasado mañana": 2, "pasado manana": 2, "day after tomorrow": 2}
        if text in offsets:
            return (self.now() + timedelta(days=offsets[text])).date().isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
            except ValueError as exc:
                raise ValueError("La fecha no existe.") from exc
        if re.fullmatch(r"\d{4}", text):
            raise ValueError("Faltan el día y el mes.")
        text = re.sub(r"^(el|la|este|esta|próximo|proximo|próxima|proxima|next|this)\s+", "", text)
        parsed = dateparser.parse(text, languages=["es", "en"], settings={
            "RELATIVE_BASE": self.now().replace(tzinfo=None), "PREFER_DATES_FROM": "future",
        })
        if parsed is None:
            raise ValueError("No se entiende la fecha. Indícala como YYYY-MM-DD.")
        # Month-only/year-only strings would otherwise inherit today's day/month.
        if not re.search(r"\d|\b(lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|"
                         r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text):
            raise ValueError("Falta el día de la fecha.")
        return parsed.date().isoformat()

    def scheduling_conflict(self, text: str) -> bool:
        if re.search(r"\b(suppose|pretend|hypothetical|imagina|supongamos|hipotético|hipotetico)\b", text, re.I):
            return True
        claim = re.search(r"\b(?:today is|hoy es|hoy estamos a)\s+([^.!?\n,;]+)", text, re.I)
        if not claim:
            return False
        try:
            return self.resolve(claim[1]) != self.context()["date"]
        except ValueError:
            return True

    def clarification(self, text: str) -> str | None:
        if re.search(r"\b(suppose|pretend|hypothetical|imagina|supongamos|hipotético|hipotetico)\b", text, re.I):
            return None
        if not self.scheduling_conflict(text):
            return None
        current = self.context()
        if re.search(r"\b(hoy|fecha|noviembre)\b", text, re.I):
            return (f"El reloj de tu dispositivo indica {current['date']} ({current['timezone']}), "
                    "no la fecha que has indicado. No he cambiado el reloj ni tus tareas. "
                    "¿Quieres referirte a esa fecha como una hipótesis o programar algo para un día concreto?")
        return (f"Your device clock says {current['date']} ({current['timezone']}), "
                "which differs from the date you stated. I have not changed the clock or your tasks. "
                "Do you mean a hypothetical date, or would you like to schedule something for a specific day?")
