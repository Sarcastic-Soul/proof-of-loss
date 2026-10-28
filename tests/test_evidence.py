from datetime import datetime

from proof_of_loss import config, evidence
from helpers import jpeg_with_exif


def day(precip, code=1, gust=10):
    return {"date": "2026-10-26", "precip_mm": precip, "weather_code": code, "max_gust_kmh": gust}


def test_read_exif_time_and_gps():
    out = evidence.read_exif(jpeg_with_exif("2026:10:27 07:42:00", 23.52, 77.81))
    assert out["taken_at"] == "2026-10-27T07:42:00+05:30"
    assert abs(out["lat"] - 23.52) < 1e-3 and abs(out["lon"] - 77.81) < 1e-3


def test_read_exif_missing():
    out = evidence.read_exif(jpeg_with_exif())
    assert "taken_at" not in out and "lat" not in out


def test_hail_verdicts():
    assert evidence.weather_verdict("hailstorm", [day(0), day(12, 95, 50)])[0] == "supported"
    assert evidence.weather_verdict("hailstorm", [day(0), day(0.2)])[0] == "contradicted"
    assert evidence.weather_verdict("hailstorm", [day(0, 0, 40)])[0] == "contradicted"
    assert evidence.weather_verdict("hailstorm", [day(3), day(1)])[0] == "inconclusive"


def test_rain_and_other_verdicts():
    assert evidence.weather_verdict("inundation", [day(40)])[0] == "supported"
    assert evidence.weather_verdict("inundation", [day(1)])[0] == "contradicted"
    assert evidence.weather_verdict("landslide", [day(0)])[0] == "inconclusive"
    assert evidence.weather_verdict("natural_fire", [day(0)])[0] == "inconclusive"


def test_deadline_uses_earliest_time_of_day():
    now = datetime(2026, 10, 28, 10, 0, tzinfo=config.IST)
    info = evidence.deadline_info("2026-10-27", "night", now)
    assert info["report_by"].startswith("2026-10-30T19:00")
    assert info["hours_left"] == 57.0 and info["status"] == "ok"
    late = evidence.deadline_info("2026-10-20", "morning", now)
    assert late["status"] == "late"
