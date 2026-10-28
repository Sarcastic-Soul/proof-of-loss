"""Short visual description of a farm photo.

In testing every available model made mistakes judging damage from a single
photo, so this text only goes into the packet as a note. It never decides
whether a claim is valid.
"""

import io
import json
import re

import boto3
from PIL import Image

from . import config

PROMPT = """This photo was sent by a farmer reporting crop damage. Describe only what
is visible. Answer with JSON only:
{"crop": "<crop or unknown>", "visible_damage": "<one short sentence, or 'none visible'>",
 "photo_quality": "<good|blurry|too dark|too far|not a field>"}"""


def shrink(data: bytes, max_side: int = 1024) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def describe_photo(data: bytes) -> dict:
    client = boto3.client("bedrock-runtime", region_name=config.REGION)
    try:
        resp = client.converse(
            modelId=config.VISION_MODEL_ID,
            messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": shrink(data)}}},
                {"text": PROMPT}]}],
            inferenceConfig={"maxTokens": 200, "temperature": 0.1},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        match = re.search(r"\{.*\}", text, re.S)
        return json.loads(match.group(0)) if match else {"visible_damage": text[:200]}
    except Exception as e:  # noqa: BLE001 - a failed description must not block the claim
        return {"error": f"photo description unavailable: {type(e).__name__}"}
