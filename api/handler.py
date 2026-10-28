"""Public HTTP API for the web app (Lambda function URL behind CloudFront).

Routes (the /api prefix is optional):
    POST /api/claims       -> {"claim_id"}
    POST /api/upload-url   {"claim_id"} -> presigned S3 POST for one photo
    POST /api/chat         {"claim_id", "message", "photos", "file_anyway", "lang"} -> agent reply
    POST /api/packet       {"claim_id"} -> fresh link to the claim packet

The agent runs on AgentCore Runtime; the claim id doubles as the runtime session id,
so every turn of one claim lands in the same session.
"""

import base64
import json
import os
import re
import uuid

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = os.environ["RUNTIME_ARN"]
BUCKET = os.environ["BUCKET"]

MAX_MESSAGE_CHARS = 2000
MAX_PHOTOS_PER_TURN = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
CLAIM_ID = re.compile(r"^claim-[0-9a-f]{32}$")

s3 = boto3.client("s3", region_name=REGION)
agentcore = boto3.client("bedrock-agentcore", region_name=REGION,
                         config=Config(read_timeout=120, retries={"max_attempts": 1}))


class BadRequest(Exception):
    pass


def respond(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False)}


def parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BadRequest("body must be JSON") from e
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


def claim_id_from(body: dict) -> str:
    claim_id = str(body.get("claim_id", ""))
    if not CLAIM_ID.match(claim_id):
        raise BadRequest("claim_id missing or malformed; call POST /api/claims first")
    return claim_id


def new_claim(_body: dict) -> dict:
    return {"claim_id": f"claim-{uuid.uuid4().hex}"}


def upload_url(body: dict) -> dict:
    claim_id = claim_id_from(body)
    key = f"photos/{claim_id}/{uuid.uuid4().hex}.jpg"
    post = s3.generate_presigned_post(
        BUCKET, key,
        Fields={"Content-Type": "image/jpeg"},
        Conditions=[{"Content-Type": "image/jpeg"},
                    ["content-length-range", 1, MAX_PHOTO_BYTES]],
        ExpiresIn=900)
    return {"key": key, "url": post["url"], "fields": post["fields"]}


def chat(body: dict) -> dict:
    claim_id = claim_id_from(body)
    message = str(body.get("message", ""))[:MAX_MESSAGE_CHARS]
    photos = body.get("photos") or []
    if not isinstance(photos, list) or len(photos) > MAX_PHOTOS_PER_TURN:
        raise BadRequest(f"photos must be a list of at most {MAX_PHOTOS_PER_TURN}")
    clean_photos = []
    for photo in photos:
        key = str((photo or {}).get("key", ""))
        if not key.startswith(f"photos/{claim_id}/"):
            raise BadRequest("photo key does not belong to this claim")
        device = photo.get("device") if isinstance(photo.get("device"), dict) else {}
        clean_photos.append({"key": key, "device": {
            k: device[k] for k in ("lat", "lon", "accuracy_m", "captured_at") if k in device}})
    if not message and not clean_photos and not body.get("file_anyway"):
        raise BadRequest("send a message, a photo, or file_anyway")

    lang = body.get("lang") if body.get("lang") in ("en", "hi", "mix") else None
    payload = {"claim_id": claim_id, "message": message, "photos": clean_photos,
               "file_anyway": bool(body.get("file_anyway")), "lang": lang}
    result = agentcore.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN, runtimeSessionId=claim_id,
        contentType="application/json", accept="application/json",
        payload=json.dumps(payload).encode())
    out = json.loads(result["response"].read())

    # Links signed inside the runtime die with its short-lived credentials; sign here instead.
    packet_key = (out.get("claim") or {}).get("packet_key")
    if packet_key:
        out["packet_url"] = s3.generate_presigned_url(
            "get_object", Params={"Bucket": BUCKET, "Key": packet_key}, ExpiresIn=3600)
    return out


def packet(body: dict) -> dict:
    key = f"packets/{claim_id_from(body)}.html"
    return {"url": s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=3600)}


ROUTES = {("POST", "/claims"): new_claim, ("POST", "/upload-url"): upload_url,
          ("POST", "/chat"): chat, ("POST", "/packet"): packet}


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "").removeprefix("/api") or "/"
    route = ROUTES.get((method, path.rstrip("/") or "/"))
    if not route:
        return respond(404, {"error": "not found"})
    try:
        return respond(200, route(parse_body(event)))
    except BadRequest as e:
        return respond(400, {"error": str(e)})
