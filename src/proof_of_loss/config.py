"""Runtime settings, read from environment variables."""

import os
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("POL_MODEL_ID", "us.amazon.nova-pro-v1:0")
VISION_MODEL_ID = os.getenv("POL_VISION_MODEL_ID", MODEL_ID)

# "local" keeps everything under DATA_DIR; "aws" uses S3 + DynamoDB.
BACKEND = os.getenv("POL_BACKEND", "local")
DATA_DIR = os.getenv("POL_DATA_DIR", ".data")
BUCKET = os.getenv("POL_BUCKET", "")
TABLE = os.getenv("POL_TABLE", "")

# PMFBY: localized losses must be reported within 72 hours.
REPORT_WINDOW_HOURS = 72
PMFBY_HELPLINE = "14447"
PMFBY_CHANNELS = [
    "Call the Krishi Rakshak helpline 14447 and keep the ticket number you get by SMS",
    "Report in the Crop Insurance app (geo-tagged photo)",
    "Tell your bank branch, the insurance company, or the local agriculture office",
]

CROPS = [
    "wheat", "rice", "maize", "soybean", "cotton", "mustard", "gram", "pigeon_pea",
    "groundnut", "sugarcane", "bajra", "jowar", "onion", "potato", "tomato", "other",
]
PERILS = [
    "hailstorm", "inundation", "landslide", "cloud_burst", "natural_fire",
    "unseasonal_rain", "cyclonic_rain",
]
