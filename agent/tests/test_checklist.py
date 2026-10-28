from proof_of_loss.checklist import gate_problems
from proof_of_loss.store import new_claim


def full_claim():
    c = new_claim("t1")
    c["farmer"] = {"name": "Ramesh", "village": "Khajuri", "district": "Vidisha", "state": "MP"}
    c["loss"] = {"crop": "wheat", "peril": "hailstorm", "area_acres": 2, "loss_date": "2026-10-27",
                 "time_of_day": "night"}
    c["photos"]["P1"] = {"key": "k", "inspected": True, "taken_at": "2026-10-28T07:00:00+05:30",
                         "location": {"lat": 23.5, "lon": 77.8, "source": "exif"}}
    c["weather"] = {"verdict": "supported"}
    return c


def test_complete_claim_passes():
    assert gate_problems(full_claim()) == []


def test_missing_fields_and_weather():
    c = full_claim()
    c["farmer"].pop("village")
    c["weather"] = None
    problems = gate_problems(c)
    assert "farmer village" in problems
    assert any("weather not checked" in p for p in problems)


def test_old_photo_blocked():
    c = full_claim()
    c["photos"]["P1"]["taken_at"] = "2026-10-20T07:00:00+05:30"
    assert any("taken after the loss" in p for p in gate_problems(c))


def test_contradicted_needs_farmer_button():
    c = full_claim()
    c["weather"] = {"verdict": "contradicted"}
    assert any("File anyway" in p for p in gate_problems(c))
    c["mismatch_confirmed_by_farmer"] = True
    assert gate_problems(c) == []


def test_script_hint_follows_farmer_words_over_app_language():
    from proof_of_loss.service import script_hint

    assert "Devanagari script" in script_hint("कल ओले पड़े", "en")
    assert "Hinglish" in script_hint("kal raat ole pade, meri fasal barbaad", "en")
    assert "English" in script_hint("Hail last night destroyed my paddy", "mix")
    assert "English" in script_hint("Sunita, Cuttack", "en")
    assert script_hint("", "en") == "[Reply in simple English only]"
    assert script_hint("", None) is None
