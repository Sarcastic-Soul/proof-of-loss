"""Chat with the agent locally.

    uv run proof-of-loss --claim demo-1
    > /photo path/to/field.jpg        attach a photo (optionally: /photo file.jpg 23.52 77.81)
    > /anyway                         press the "File anyway" button
    > /claim                          show the stored claim summary
"""

import argparse
import base64
import json
import uuid
from datetime import datetime

from . import config
from .service import handle_turn
from .store import default_stores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", default=f"cli-{uuid.uuid4().hex[:8]}")
    args = ap.parse_args()
    claims, blobs = default_stores()
    print(f"claim {args.claim} (model {config.MODEL_ID}). Ctrl-D to quit.")
    photos, anyway = [], False
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if line.startswith("/photo "):
            parts = line.split()
            photo = {"data_b64": base64.b64encode(open(parts[1], "rb").read()).decode()}
            if len(parts) == 4:
                photo["device"] = {"lat": float(parts[2]), "lon": float(parts[3]),
                                   "captured_at": datetime.now(config.IST).isoformat()}
            photos.append(photo)
            print(f"  queued {parts[1]}")
            continue
        if line == "/anyway":
            anyway = True
            line = ""
        if line == "/claim":
            print(json.dumps(claims.get(args.claim), indent=2, ensure_ascii=False)[:3000])
            continue
        out = handle_turn(args.claim, line, claims, blobs, photos=photos, file_anyway=anyway)
        photos, anyway = [], False
        print("\n" + out["reply"] + "\n")
        if out["claim"]["open_items"]:
            print("  open:", "; ".join(out["claim"]["open_items"]))
        if out.get("packet_url"):
            print("  packet:", out["packet_url"])
