"""What a claim needs before a packet can be made.

Shared by the tools (to tell the agent what is still missing) and the steering
handler (to block the packet until everything is in place).
"""

from datetime import datetime, timedelta

from .evidence import loss_start

FARMER_FIELDS = ["name", "village", "district", "state"]
# time_of_day is optional: "unknown" starts the 72 hours at midnight, the safe side.
LOSS_FIELDS = ["crop", "peril", "area_acres", "loss_date"]


def missing_details(claim: dict) -> list[str]:
    missing = [f"farmer {f}" for f in FARMER_FIELDS if not claim["farmer"].get(f)]
    missing += [f"loss {f}" for f in LOSS_FIELDS if not claim["loss"].get(f)]
    return missing


def photo_problems(claim: dict) -> list[str]:
    photos = claim["photos"]
    if not photos:
        return ["no photo uploaded yet"]
    checked = [p for p in photos.values() if p.get("inspected")]
    if not checked:
        return ["photos not inspected yet (call inspect_photo)"]
    problems = []
    if not any(p.get("location") for p in checked):
        problems.append("no photo has a location (ask for a photo taken in the app with location on)")
    loss = claim["loss"]
    if loss.get("loss_date"):
        start = loss_start(loss["loss_date"], loss.get("time_of_day") or "unknown")
        fresh = [p for p in checked if p.get("taken_at")
                 and datetime.fromisoformat(p["taken_at"]) >= start - timedelta(hours=12)]
        if not fresh:
            problems.append("no photo was taken after the loss (ask for a new photo of the field)")
    return problems


def gate_problems(claim: dict) -> list[str]:
    """Everything that blocks the claim packet, in the order to fix it."""
    problems = missing_details(claim) + photo_problems(claim)
    weather = claim.get("weather")
    if not weather:
        problems.append("weather not checked yet (call check_weather)")
    elif weather["verdict"] == "contradicted" and not claim.get("mismatch_confirmed_by_farmer"):
        problems.append(
            "weather record does not show the reported peril; explain this to the farmer and "
            "ask them to press the 'File anyway' button if they still want to file. "
            "The packet will then ask for a field inspection")
    return problems
