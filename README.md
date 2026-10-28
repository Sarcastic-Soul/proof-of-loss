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
  model made mistakes judging damage from one photo.

## Run locally

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), and AWS credentials with Bedrock
access to `us.amazon.nova-pro-v1:0` in us-east-1.

```bash
cd agent
uv sync
uv run pytest                      # unit tests, no AWS calls
uv run python scripts/e2e.py       # three scripted claims against Bedrock (a few cents)
uv run proof-of-loss               # chat; /photo file.jpg [lat lon], /anyway, /claim
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `POL_MODEL_ID` | `us.amazon.nova-pro-v1:0` | Bedrock model for the agent |
| `POL_BACKEND` | `local` | `local` (files under the repo's `.data/`) or `aws` (S3 + DynamoDB) |
| `POL_BUCKET`, `POL_TABLE` | | S3 bucket and DynamoDB table for `aws` |

## Repository layout

```
agent/       Strands agent (Python package, tests, scripts); deployed as the AgentCore runtime code
api/         Lambda behind a function URL: claim ids, photo upload links, chat turns
web/         static web app, served by CloudFront
agentcore/   AgentCore CLI project: agentcore.json, deploy target, CDK stack (agentcore/cdk/lib/cdk-stack.ts)
```

## Deploy to AWS

Needs Node.js 20+, the AgentCore CLI (`npm install -g @aws/agentcore`), and credentials
for the account in `agentcore/aws-targets.json`.

```bash
(cd agentcore/cdk && npm install)
agentcore deploy --target default
```

One stack holds everything, all pay-per-use:

```
browser -> CloudFront -> S3 (web app)
                    \-> /api/* -> Lambda function URL -> AgentCore Runtime (Strands agent)
                                         |                       |-> Bedrock (Nova Pro)
                                         |                       |-> Open-Meteo
                                         \-> S3 (photos, packets, sessions) + DynamoDB (claims)
```

Photos go straight from the browser to S3 with a presigned POST (10 MB cap), so large
images never pass through Lambda. The claim id is also the AgentCore session id, so all
turns of one claim share a session. An AWS Budget emails at 50% and 100% of $10 a month.

The stack outputs `WebUrl` and `ApiUrl`. Quick check:

```bash
curl -X POST "$WEB_URL/api/claims" -d '{}'
curl -X POST "$WEB_URL/api/chat" -H 'content-type: application/json' \
  -d '{"claim_id": "claim-...", "message": "Kal raat ole pade, 2 acre gehun barbaad"}'
```

## Status

Work in progress for the AWS "Strands SDK: Workshop to Ship" hackathon. Deployed: agent
runtime, API, storage, placeholder web page. Still to come: web app, Hindi voice notes
(Amazon Transcribe), deadline reminders, evals.

## License

MIT. Demo photo credits in `demo/CREDITS.md`.
