"""One conversation turn: register uploads, run the agent, return the reply.

Shared by the AgentCore entrypoint (app.py) and the local CLI.
"""

import base64
from datetime import datetime

from strands.types.exceptions import MaxTokensReachedException

from . import config, evidence
from .agent import build_agent, clean_reply
from .checklist import gate_problems
from .store import BlobStore, ClaimStore
from .tools import ClaimContext


def register_photos(ctx: ClaimContext, claim: dict, photos: list[dict]) -> list[str]:
    """Each photo is {"key": <already uploaded>} or {"data_b64": ...}, plus optional
    "device": {"lat", "lon", "accuracy_m", "captured_at"} from the phone at capture time."""
    added = []
    for photo in photos:
        pid = f"P{len(claim['photos']) + 1}"
        key = photo.get("key")
        if not key:
            key = f"photos/{ctx.claim_id}/{pid}.jpg"
            ctx.blobs.write(key, base64.b64decode(photo["data_b64"]), "image/jpeg")
        claim["photos"][pid] = {"key": key, "device": photo.get("device") or {},
                                "uploaded_at": ctx.now.isoformat(timespec="seconds")}
        added.append(pid)
    return added


HINTS = {
    "en": "[Reply in simple English only]",
    "hi": "[Reply in Hindi, Devanagari script]",
    "mix": "[Reply in Hinglish written in Roman letters, like the farmer. Do not use "
           "Devanagari. Copy names exactly as written]",
}
# Common words that tell English from Hinglish when both use Roman letters.
ENGLISH_WORDS = {"the", "i", "my", "is", "was", "of", "and", "last", "night", "from", "in",
                 "have", "has", "acres", "destroyed", "damaged", "please", "what", "it", "to"}
HINGLISH_WORDS = {"hai", "hain", "ki", "ka", "ke", "mera", "meri", "mere", "kal", "raat", "pade",
                  "gaya", "gayi", "nahi", "aur", "se", "ko", "main", "hua", "barbaad", "bhi"}


def script_hint(message: str, lang: str | None = None) -> str | None:
    """Nova Pro tends to answer Roman-script Hinglish (and sometimes English) in
    Devanagari, and then mis-spells names. Tell it which language to use on every
    turn. The farmer's own words decide; the app's language breaks ties and covers
    photo-only turns."""
    letters = [ch for ch in message if ch.isalpha()]
    if not letters:
        return HINTS.get(lang)
    if sum(1 for ch in letters if "\u0900" <= ch <= "\u097f") / len(letters) > 0.5:
        return HINTS["hi"]
    words = [w.strip(".,!?").lower() for w in message.split()]
    english = sum(w in ENGLISH_WORDS for w in words)
    hinglish = sum(w in HINGLISH_WORDS for w in words)
    if english != hinglish:
        return HINTS["en" if english > hinglish else "mix"]
    return HINTS["en" if lang == "en" else "mix"]


def summary(claim: dict, now: datetime) -> dict:
    loss = claim["loss"]
    deadline = (evidence.deadline_info(loss["loss_date"], loss.get("time_of_day", "unknown"), now)
                if loss.get("loss_date") else None)
    return {
        "claim_id": claim["claim_id"],
        "status": claim["status"],
        "farmer": claim["farmer"],
        "loss": loss,
        "photos": {pid: {k: p.get(k) for k in ("taken_at", "location", "flags", "inspected")}
                   for pid, p in claim["photos"].items()},
        "weather": {k: claim["weather"][k] for k in ("verdict", "reason")} if claim["weather"] else None,
        "deadline": deadline,
        "open_items": gate_problems(claim),
        "can_file_anyway": bool(claim["weather"] and claim["weather"]["verdict"] == "contradicted"
                                and not claim["mismatch_confirmed_by_farmer"]),
        "packet_key": claim["packet_key"],
    }


def handle_turn(claim_id: str, message: str, claims: ClaimStore, blobs: BlobStore,
                photos: list[dict] | None = None, file_anyway: bool = False,
                now: datetime | None = None, model=None, lang: str | None = None) -> dict:
    ctx = ClaimContext(claim_id, claims, blobs, now or datetime.now(config.IST))
    claim = ctx.load()
    notes = []
    if photos:
        added = register_photos(ctx, claim, photos)
        notes.append(f"[Farmer uploaded photos: {', '.join(added)}]")
    if file_anyway and claim.get("weather"):
        # Only the app sets this, from a button the farmer presses; the model cannot.
        claim["mismatch_confirmed_by_farmer"] = True
        notes.append("[Farmer pressed 'File anyway' after seeing the weather mismatch]")
    ctx.save(claim)

    hint = script_hint(message, lang)
    if hint:
        notes.append(hint)
    prompt = "\n".join(notes + [message]).strip() or "(no text)"
    agent = build_agent(ctx, model=model)
    try:
        text = clean_reply(str(agent(prompt)))
    except MaxTokensReachedException:
        # Tool results are already saved; only the reply text was cut off.
        text = "Sorry, my answer got too long. Please check the claim details below or ask again."
    claim = ctx.load()
    reply = {"reply": text, "claim": summary(claim, ctx.now)}
    if claim["packet_key"]:
        reply["packet_url"] = blobs.url(claim["packet_key"])
    return reply
