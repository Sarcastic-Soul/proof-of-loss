"""Evidence checks that do not need a model: photo EXIF, weather, deadline."""

import io
import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta

from PIL import Image

from . import config

# Earliest plausible start of each part of the day. Using the earliest time keeps
# the 72-hour countdown on the safe side for the farmer.
TIME_OF_DAY_START = {
    "early_morning": time(3, 0),
    "morning": time(6, 0),
    "afternoon": time(12, 0),
    "evening": time(16, 0),
    "night": time(19, 0),
    "unknown": time(0, 0),
}


# ---------------------------------------------------------------- photo EXIF

def read_exif(data: bytes) -> dict:
    """Return taken_at (ISO, IST if no offset), lat, lon and camera, when present."""
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    out: dict = {"width": img.width, "height": img.height}
    if not exif:
        return out
    sub = exif.get_ifd(0x8769)
    raw = sub.get(36867) or exif.get(306)  # DateTimeOriginal, else DateTime
    if raw:
        try:
            taken = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            offset = sub.get(36881)  # OffsetTimeOriginal, e.g. "+05:30"
            if offset:
                taken = datetime.fromisoformat(taken.isoformat() + str(offset).strip())
            else:
                taken = taken.replace(tzinfo=config.IST)
            out["taken_at"] = taken.isoformat()
        except ValueError:
            pass
    gps = exif.get_ifd(0x8825)
    if gps.get(2) and gps.get(4):
        lat = _dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
        lon = _dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
        out["lat"], out["lon"] = round(lat, 5), round(lon, 5)
    model = exif.get(272)
    if model:
        out["camera"] = str(model).strip("\x00 ")
    return out


def _dms(value) -> float:
    d, m, s = (float(x) for x in value)
    return d + m / 60 + s / 3600


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------- weather

def fetch_daily_weather(lat: float, lon: float, start: date, end: date, today: date) -> dict:
    """Daily rain, weather code and gusts from Open-Meteo (free, no key)."""
    recent = (today - start).days <= 90
    base = ("https://api.open-meteo.com/v1/forecast" if recent
            else "https://archive-api.open-meteo.com/v1/archive")
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "precipitation_sum,weather_code,wind_gusts_10m_max",
        "timezone": "Asia/Kolkata",
    })
    with urllib.request.urlopen(f"{base}?{query}", timeout=15) as resp:
        body = json.load(resp)
    d = body["daily"]
    days = [
        {"date": t, "precip_mm": p or 0.0, "weather_code": c, "max_gust_kmh": g}
        for t, p, c, g in zip(d["time"], d["precipitation_sum"], d["weather_code"],
                              d["wind_gusts_10m_max"])
    ]
    return {"source": "Open-Meteo " + ("forecast model (recent days)" if recent else "ERA5 archive"),
            "grid_lat": body["latitude"], "grid_lon": body["longitude"], "days": days}


THUNDER = {95, 96, 99}


def weather_verdict(peril: str, days: list[dict]) -> tuple[str, str]:
    """Return (verdict, reason). Verdict is supported, inconclusive or contradicted.

    Weather grids are about 10 km wide and can miss a local hailstorm, so a
    contradiction never rejects a claim; it only asks for a field inspection.
    """
    total = sum(d["precip_mm"] for d in days)
    wettest = max((d["precip_mm"] for d in days), default=0.0)
    gust = max((d["max_gust_kmh"] or 0 for d in days), default=0.0)
    storm = any(d["weather_code"] in THUNDER for d in days)
    summary = f"{total:.1f} mm rain over {len(days)} days, wettest day {wettest:.1f} mm, max gust {gust:.0f} km/h"

    if peril == "hailstorm":
        if storm or (wettest >= 5 and gust >= 40):
            return "supported", f"Thunderstorm or strong rain with gusts recorded ({summary})."
        if total < 1:  # hail always falls with a rain cloud
            return "contradicted", f"No rain or storm recorded ({summary})."
        return "inconclusive", f"Some rain but no clear storm signal ({summary})."
    if peril in {"inundation", "cloud_burst", "unseasonal_rain", "cyclonic_rain"}:
        if wettest >= 35 or total >= 60:
            return "supported", f"Heavy rain recorded ({summary})."
        if total < 5:
            return "contradicted", f"Little or no rain recorded ({summary})."
        return "inconclusive", f"Moderate rain recorded ({summary})."
    if peril == "landslide":
        if total >= 30:
            return "supported", f"Heavy rain before the landslide ({summary})."
        return "inconclusive", f"Landslides can happen without heavy rain at this grid point ({summary})."
    if peril == "natural_fire":
        if storm:
            return "supported", f"Thunderstorm recorded, consistent with lightning fire ({summary})."
        return "inconclusive", f"Weather data cannot confirm or rule out a fire ({summary})."
    return "inconclusive", summary


# ------------------------------------------------------------------ deadline

def loss_start(loss_date: str, time_of_day: str) -> datetime:
    t = TIME_OF_DAY_START.get(time_of_day, TIME_OF_DAY_START["unknown"])
    return datetime.combine(date.fromisoformat(loss_date), t, tzinfo=config.IST)


def deadline_info(loss_date: str, time_of_day: str, now: datetime) -> dict:
    start = loss_start(loss_date, time_of_day)
    deadline = start + timedelta(hours=config.REPORT_WINDOW_HOURS)
    hours_left = (deadline - now).total_seconds() / 3600
    return {
        "loss_assumed_from": start.isoformat(timespec="minutes"),
        "report_by": deadline.isoformat(timespec="minutes"),
        "hours_left": round(hours_left, 1),
        "status": "late" if hours_left < 0 else "urgent" if hours_left < 24 else "ok",
    }
