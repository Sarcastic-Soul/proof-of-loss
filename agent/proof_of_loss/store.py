"""Claim records and file storage.

Local backend writes JSON and files under DATA_DIR. AWS backend uses DynamoDB
for claims and S3 for photos and packets.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from . import config


def new_claim(claim_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "created_at": datetime.now(config.IST).isoformat(timespec="seconds"),
        "status": "draft",
        "farmer": {},
        "loss": {},
        "photos": {},
        "weather": None,
        "mismatch_confirmed_by_farmer": False,
        "packet_key": None,
        "audit": [],
    }


class ClaimStore(Protocol):
    def get(self, claim_id: str) -> dict: ...
    def put(self, claim: dict) -> None: ...


class BlobStore(Protocol):
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes, content_type: str) -> None: ...
    def url(self, key: str) -> str: ...


class LocalClaimStore:
    def __init__(self, root: str = config.DATA_DIR):
        self.dir = Path(root) / "claims"
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, claim_id: str) -> dict:
        path = self.dir / f"{claim_id}.json"
        return json.loads(path.read_text()) if path.exists() else new_claim(claim_id)

    def put(self, claim: dict) -> None:
        (self.dir / f"{claim['claim_id']}.json").write_text(
            json.dumps(claim, indent=2, ensure_ascii=False))


class LocalBlobStore:
    def __init__(self, root: str = config.DATA_DIR):
        self.dir = Path(root) / "files"

    def read(self, key: str) -> bytes:
        return (self.dir / key).read_bytes()

    def write(self, key: str, data: bytes, content_type: str) -> None:
        path = self.dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def url(self, key: str) -> str:
        return (self.dir / key).resolve().as_uri()


class DynamoClaimStore:
    def __init__(self, table: str = config.TABLE):
        import boto3

        self.table = boto3.resource("dynamodb", region_name=config.REGION).Table(table)

    def get(self, claim_id: str) -> dict:
        item = self.table.get_item(Key={"claim_id": claim_id}).get("Item")
        return json.loads(json.dumps(item, default=_from_decimal)) if item else new_claim(claim_id)

    def put(self, claim: dict) -> None:
        self.table.put_item(Item=json.loads(json.dumps(claim), parse_float=Decimal))


class S3BlobStore:
    def __init__(self, bucket: str = config.BUCKET):
        import boto3

        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=config.REGION)

    def read(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def write(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def url(self, key: str) -> str:
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=7 * 24 * 3600)


def _from_decimal(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value))


def default_stores() -> tuple[ClaimStore, BlobStore]:
    if config.BACKEND == "aws":
        return DynamoClaimStore(), S3BlobStore()
    return LocalClaimStore(), LocalBlobStore()
