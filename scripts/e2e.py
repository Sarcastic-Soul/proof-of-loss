"""Scripted end-to-end runs against Bedrock (costs a few cents).

    uv run python scripts/e2e.py
"""

import base64
import io
import json
import sys
import uuid
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))
from helpers import jpeg_with_exif  # noqa: E402

from proof_of_loss.service import handle_turn  # noqa: E402
from proof_of_loss.store import LocalBlobStore, LocalClaimStore  # noqa: E402

PHOTO = Path(__file__).parents[1] / "demo" / "lodged_field.jpg"


def field_photo(taken: str, lat: float, lon: float) -> str:
    """Real field photo with EXIF time and GPS written in, as a phone camera would."""
    exif_src = Image.open(io.BytesIO(jpeg_with_exif(taken, lat, lon))).getexif()
    img = Image.open(PHOTO).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_src)
    return base64.b64encode(buf.getvalue()).decode()


def run(name: str, turns: list[dict]):
    claims, blobs = LocalClaimStore(".data/e2e"), LocalBlobStore(".data/e2e")
    claim_id = f"{name}-{uuid.uuid4().hex[:6]}"
    print(f"\n===== {name} ({claim_id})")
    for t in turns:
        print(f"\nFARMER: {t.get('message')}{' [+photo]' if t.get('photos') else ''}"
              f"{' [File anyway]' if t.get('file_anyway') else ''}")
        out = handle_turn(claim_id, t.get("message", ""), claims, blobs,
                          photos=t.get("photos"), file_anyway=t.get("file_anyway", False))
        print(f"AGENT: {out['reply']}")
        print("  open:", out["claim"]["open_items"])
    claim = claims.get(claim_id)
    print("  audit:", [(a["tool"], a["status"]) for a in claim["audit"]])
    print("  weather:", claim["weather"] and claim["weather"]["verdict"], "| packet:", claim["packet_key"])
    return claim


if __name__ == "__main__":
    supported = run("cuttack-hail", [
        {"message": "Namaste. Main Sunil Behera, gaon Kendupatna, district Cuttack, Odisha. "
                    "Kal raat bahut tez toofan aur ole pade, meri dedh acre dhaan ki fasal gir gayi. "
                    "Photo bhej raha hoon.",
         "photos": [{"data_b64": field_photo("2026:10:28 07:30:00", 20.46, 85.88)}]},
        {"message": "Haan ji, sab sahi hai. Packet bana do."},
    ])
    contradicted = run("rajkot-hail", [
        {"message": "नमस्ते, मैं रमेश पटेल हूँ, गाँव सरधार, जिला राजकोट, गुजरात। कल रात ओले गिरे "
                    "और मेरी दो एकड़ कपास बर्बाद हो गई।",
         "photos": [{"data_b64": field_photo("2026:10:28 08:10:00", 22.3, 70.8)}]},
        {"message": "पैकेट बना दो।"},
        {"message": "हाँ, मेरे खेत में सच में ओले गिरे थे। आगे बढ़ना है।", "file_anyway": True},
    ])
    old_photo = run("old-photo", [
        {"message": "Main Geeta, gaon Kendupatna, district Cuttack, Odisha. Kal raat ole pade, "
                    "1 acre dhaan kharab. Claim banana hai.",
         "photos": [{"data_b64": field_photo("2026:09:02 10:00:00", 20.46, 85.88)}]},
        {"message": "Packet bana do jaldi."},
    ])
