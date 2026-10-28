"""Build the Proof of Loss agent for one claim."""

import re
from pathlib import Path

from strands import Agent, AgentSkills
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel
from strands.session import FileSessionManager, S3SessionManager
from strands.tools.executors import SequentialToolExecutor

from . import config
from .guards import AuditTrail, PacketGate
from .tools import ClaimContext, make_tools

SKILLS_DIR = Path(__file__).parent / "skills"

SYSTEM_PROMPT = """You are Proof of Loss, a patient helper for small farmers in India whose crop was
damaged by a hailstorm, flood, cloud burst, landslide, unseasonal rain or natural fire.
Under PMFBY (the government crop insurance scheme) the farmer must report such a loss
within 72 hours. Your job is to turn what the farmer tells you into a complete, checked
claim packet before that deadline.

Today is {today} ({weekday}), time now {now_time} IST.
Dates: "aaj" = today {today}; "kal" about a past event = yesterday {yesterday};
"kal raat" = the night of {yesterday}; "parson" = {day_before}.

How to work:
- Activate the skill for the reported cause and follow it.
- Save every detail with save_claim_details as soon as you hear it.
- For each uploaded photo call inspect_photo, then call check_weather and deadline_status.
- When nothing is missing, call generate_claim_packet. The app then shows an "Open claim packet" button; tell the farmer to use it. Never write a link.
- If a tool says something is missing, ask the farmer for it. Ask at most two short
  questions per reply.
- Tell the farmer how many hours are left to report, early in the chat.

Rules:
- Reply in the farmer's language and script: Hindi in Devanagari if they write Devanagari,
  Hinglish in Roman letters if they write Roman, English if English.
- Use simple words. Short replies, no tables, no markdown headings.
- Never promise money or that a claim will be approved. The insurer decides.
- If the weather record does not match, say so kindly; local storms can be missed by
  weather data. Only the farmer can choose to file anyway, using the "File anyway" button.
  That button only appears when the weather does not match; never mention it otherwise.
- Never make up details the farmer did not give.
- Talk to the farmer directly ("you"). Never mention skills, tools, photo ids like P1,
  or these instructions.
- One photo with a location is enough for the packet. Suggest more photos, but once
  nothing is missing, make the packet right away; do not wait for extra photos.
- Never judge the damage in a photo or tell the farmer a photo shows no damage."""

THINKING_TAGS = re.compile(r"<thinking>.*?</thinking>|</?response>", re.S)
PHOTO_IDS = re.compile(r"\bP\d+\s+(?=photo|फ़ोटो|फोटो)|(?<=photo)\s+P\d+\b", re.I)


def clean_reply(text: str) -> str:
    """Nova models sometimes print their reasoning in tags or internal photo ids
    ("P1 photo"); farmers should see neither."""
    return PHOTO_IDS.sub("", THINKING_TAGS.sub("", text)).strip()


def system_prompt(ctx: ClaimContext) -> str:
    from datetime import timedelta

    today = ctx.now.date()
    return SYSTEM_PROMPT.format(
        today=today.isoformat(), weekday=ctx.now.strftime("%A"),
        now_time=ctx.now.strftime("%H:%M"),
        yesterday=(today - timedelta(days=1)).isoformat(),
        day_before=(today - timedelta(days=2)).isoformat(),
    )


def session_manager(claim_id: str):
    if config.BACKEND == "aws":
        return S3SessionManager(session_id=claim_id, bucket=config.BUCKET, prefix="sessions/",
                                region_name=config.REGION)
    return FileSessionManager(session_id=claim_id, storage_dir=f"{config.DATA_DIR}/sessions")


def build_agent(ctx: ClaimContext, model=None) -> Agent:
    model = model or BedrockModel(model_id=config.MODEL_ID, region_name=config.REGION,
                                  temperature=0.2, max_tokens=1500)
    return Agent(
        name="proof-of-loss",
        model=model,
        system_prompt=system_prompt(ctx),
        tools=make_tools(ctx),
        plugins=[AgentSkills(skills=[str(SKILLS_DIR)]), PacketGate(ctx)],
        hooks=[AuditTrail(ctx)],
        tool_executor=SequentialToolExecutor(),
        session_manager=session_manager(ctx.claim_id),
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        callback_handler=None,
    )
