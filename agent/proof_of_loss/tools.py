"""Agent tools. Each claim gets its own tool set bound to that claim's record."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from strands import tool

from . import config, evidence, packet, vision
from .checklist import gate_problems, missing_details, photo_problems
from .store import BlobStore, ClaimStore

Crop = Literal[tuple(config.CROPS)]
Peril = Literal[tuple(config.PERILS)]
TimeOfDay = Literal[tuple(evidence.TIME_OF_DAY_START)]


@dataclass
class ClaimContext:
    claim_id: str
    claims: ClaimStore
    blobs: BlobStore
    now: datetime = field(default_factory=lambda: datetime.now(config.IST))

    def load(self) -> dict:
        return self.claims.get(self.claim_id)

    def save(self, claim: dict) -> None:
        self.claims.put(claim)


def make_tools(ctx: ClaimContext) -> list:
    @tool
    def save_claim_details(
        farmer_name: str | None = None,
        village: str | None = None,
        district: str | None = None,
        state: str | None = None,
        crop: Crop | None = None,
        peril: Peril | None = None,
        area_acres: float | None = None,
        loss_date: str | None = None,
        time_of_day: TimeOfDay | None = None,
        description: str | None = None,
    ) -> dict:
        """Save what the farmer told you about the loss. Call it as soon as you learn
        any detail; pass only the fields you know. Returns what is still missing.

        Args:
            farmer_name: Farmer's name.
            village: Village name.
            district: District name.
            state: Indian state.
            crop: Damaged crop, in English.
            peril: Cause of loss.
            area_acres: Damaged area in acres (1 bigha is about 0.62 acre in MP; ask if unsure).
            loss_date: Date of the loss, YYYY-MM-DD. Work it out from words like "kal raat".
            time_of_day: Part of the day the loss happened.
            description: One or two sentences in English describing the damage.
        """
        claim = ctx.load()
        farmer = {"name": farmer_name, "village": village, "district": district, "state": state}
        loss = {"crop": crop, "peril": peril, "area_acres": area_acres, "loss_date": loss_date,
                "time_of_day": time_of_day, "description": description}
        if loss_date:
            try:
                day = date.fromisoformat(loss_date)
            except ValueError:
                return {"error": "loss_date must be YYYY-MM-DD"}
            if day > ctx.now.date():
                return {"error": f"loss_date {loss_date} is in the future; today is {ctx.now.date()}"}
        if area_acres is not None and not 0 < area_acres <= 100:
            return {"error": "area_acres must be between 0 and 100"}
        claim["farmer"].update({k: v for k, v in farmer.items() if v})
        claim["loss"].update({k: v for k, v in loss.items() if v is not None})
        if loss_date or peril:
            claim["weather"] = None  # inputs changed, so the old check no longer applies
        ctx.save(claim)
        return {"saved": True, "still_missing": missing_details(claim) + photo_problems(claim)}

    @tool
    def inspect_photo(photo_id: str) -> dict:
        """Read time and GPS from a photo the farmer uploaded, and describe what it shows.

        Args:
            photo_id: Photo id, as listed in the message (for example P1).
        """
        claim = ctx.load()
        photo = claim["photos"].get(photo_id)
        if not photo:
            return {"error": f"no photo {photo_id}; uploaded photos: {list(claim['photos'])}"}
        data = ctx.blobs.read(photo["key"])
        exif = evidence.read_exif(data)
        device = photo.get("device") or {}
        photo["exif"] = exif
        photo["taken_at"] = exif.get("taken_at") or device.get("captured_at")
        photo["time_source"] = "exif" if exif.get("taken_at") else "app" if device.get("captured_at") else None
        if "lat" in exif:
            photo["location"] = {"lat": exif["lat"], "lon": exif["lon"], "source": "exif"}
        elif device.get("lat") is not None:
            photo["location"] = {"lat": device["lat"], "lon": device["lon"], "source": "app",
                                 "accuracy_m": device.get("accuracy_m")}
        else:
            photo["location"] = None
        photo["vision"] = vision.describe_photo(data)
        photo["inspected"] = True

        flags = []
        if exif.get("lat") is not None and device.get("lat") is not None:
            gap = evidence.distance_km(exif["lat"], exif["lon"], device["lat"], device["lon"])
            photo["exif_vs_app_km"] = round(gap, 2)
            if gap > 5:
                flags.append(f"photo GPS is {gap:.1f} km from where it was uploaded")
        if photo["taken_at"]:
            age = ctx.now - datetime.fromisoformat(photo["taken_at"])
            if age > timedelta(days=15):
                flags.append(f"photo is {age.days} days old")
        photo["flags"] = flags
        ctx.save(claim)
        return {k: photo.get(k) for k in ("taken_at", "time_source", "location", "vision", "flags")}

    @tool
    def check_weather() -> dict:
        """Check recorded weather at the photo location around the loss date, and
        whether it supports the reported cause. Needs loss date, peril and an
        inspected photo with a location."""
        claim = ctx.load()
        loss = claim["loss"]
        located = [p for p in claim["photos"].values() if p.get("location")]
        if not (loss.get("loss_date") and loss.get("peril") and located):
            return {"error": "need loss_date, peril and an inspected photo with location first",
                    "still_missing": missing_details(claim) + photo_problems(claim)}
        loc = located[0]["location"]
        day = date.fromisoformat(loss["loss_date"])
        try:
            data = evidence.fetch_daily_weather(loc["lat"], loc["lon"], day - timedelta(days=1),
                                                min(day + timedelta(days=1), ctx.now.date()),
                                                ctx.now.date())
        except Exception as e:  # noqa: BLE001
            return {"error": f"weather service unavailable ({type(e).__name__}); try again"}
        verdict, reason = evidence.weather_verdict(loss["peril"], data["days"])
        claim["weather"] = {**data, "lat": loc["lat"], "lon": loc["lon"], "peril": loss["peril"],
                            "verdict": verdict, "reason": reason}
        ctx.save(claim)
        return {"verdict": verdict, "reason": reason, "days": data["days"], "source": data["source"]}

    @tool
    def deadline_status() -> dict:
        """Hours left in the 72-hour PMFBY reporting window, and how to report."""
        loss = ctx.load()["loss"]
        if not loss.get("loss_date"):
            return {"error": "loss_date not saved yet"}
        info = evidence.deadline_info(loss["loss_date"], loss.get("time_of_day", "unknown"), ctx.now)
        return {**info, "how_to_report": config.PMFBY_CHANNELS}

    @tool
    def generate_claim_packet() -> dict:
        """Build the claim packet (an HTML page the farmer can print or show) once all
        evidence is in place. Returns a link."""
        claim = ctx.load()
        problems = gate_problems(claim)
        if problems:  # steering normally stops this earlier; keep the tool safe on its own
            return {"error": "claim not ready", "problems": problems}
        html = packet.render(claim, ctx.blobs, ctx.now)
        key = f"packets/{claim['claim_id']}.html"
        ctx.blobs.write(key, html.encode(), "text/html; charset=utf-8")
        claim["packet_key"] = key
        claim["status"] = "packet_ready"
        ctx.save(claim)
        # No URL here: signed links are long and the model would copy them into
        # its reply. The app shows the farmer an "Open claim packet" button.
        return {"packet_ready": True,
                "deadline": evidence.deadline_info(claim["loss"]["loss_date"],
                                                   claim["loss"]["time_of_day"], ctx.now),
                "next_step": config.PMFBY_CHANNELS}

    return [save_claim_details, inspect_photo, check_weather, deadline_status, generate_claim_packet]
