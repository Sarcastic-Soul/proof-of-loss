# Proof of Loss

A Strands Agents SDK agent that helps small farmers in India report crop damage in time
and with evidence that holds up.

Under PMFBY, India's government crop insurance scheme, a farmer hit by a localized
calamity (hailstorm, inundation, landslide, cloud burst, natural fire) must report the
loss within **72 hours**. Many miss the window or file with weak evidence. Proof of Loss
lets a farmer describe the damage in Hindi, Hinglish or English, upload photos, and get a
printable claim packet with the deadline, photo time and GPS, a weather check, and a
record of every step.

## How it works

```
farmer message + photos
        |
  Strands agent (Amazon Nova Pro on Bedrock)
        |-- skills: one SKILL.md per cause of loss (what to ask, what photos to request)
        |-- tools:
        |     save_claim_details   fields with fixed lists for crop and cause
        |     inspect_photo        EXIF time + GPS, app GPS fallback, short visual note
        |     check_weather        Open-Meteo rain, thunderstorm codes, gusts near the loss date
        |     deadline_status      hours left in the 72-hour window
        |     generate_claim_packet
        |-- steering (PacketGate): blocks the packet until the checklist passes
        |-- hook (AuditTrail): logs every tool call into the packet
        |
  claim record (JSON locally, DynamoDB on AWS) + packet (HTML)
```

Rules the model cannot get around, because they live in code:

- No packet without farmer details, crop, cause, area, loss date, a photo with a
  location, and a photo taken after the loss.
- If the weather record shows no rain or storm, the packet stays blocked until the
  farmer presses **File anyway** in the app. The model cannot set that flag. The packet
  then asks for a field inspection, since weather grids are about 10 km wide and can miss
  a local hailstorm. The agent never rejects a farmer.
- Photo damage descriptions are notes, not judgements. In our tests every available
  model made mistakes judging damage from one photo (see `../model-probe`).

## Run locally

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), and AWS credentials with Bedrock
access to `us.amazon.nova-pro-v1:0` in us-east-1.

```bash
uv sync
uv run pytest                      # unit tests, no AWS calls
uv run python scripts/e2e.py       # three scripted claims against Bedrock (a few cents)
uv run proof-of-loss               # chat; /photo file.jpg [lat lon], /anyway, /claim
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `POL_MODEL_ID` | `us.amazon.nova-pro-v1:0` | Bedrock model for the agent |
| `POL_BACKEND` | `local` | `local` (files under `.data/`) or `aws` (S3 + DynamoDB) |
| `POL_BUCKET`, `POL_TABLE` | | S3 bucket and DynamoDB table for `aws` |

## Status

Work in progress for the AWS "Strands SDK: Workshop to Ship" hackathon. Still to come:
AgentCore deployment, web app, Hindi voice notes (Amazon Transcribe), deadline
reminders, evals.

## License

MIT. Demo photo credits in `demo/CREDITS.md`.
