# Proof of Loss: a Strands agent that helps farmers claim crop insurance in 72 hours

**Live app:** https://d39zeolevac0dg.cloudfront.net
**Code (MIT):** https://github.com/Sarcastic-Soul/proof-of-loss
**Demo video:** VIDEO_LINK

## The problem

PMFBY is India's government crop insurance scheme. One part of it pays for *localized* damage: a hailstorm that flattens one village's wheat, a
flash flood, a landslide, a field fire. The catch is a hard rule. The farmer has to
report the loss within **72 hours**, by calling the helpline 14447, through the Crop
Insurance app, or at a bank or agriculture office.

In practice farmers miss that window or file weak claims. They don't know the rule
exists, they don't know what to say, their photos have no time or place, and nobody
checks whether the weather that day backs up the story. A claim that comes in late or
thin often gets rejected, and the farmer loses a season's income.

Proof of Loss is a chat app for that moment. The farmer types or speaks in Hindi,
Hinglish or English ("Kal raat ole pade, 2 acre gehun barbaad"), sends a photo of the
field, and gets back:

- a countdown of the hours left to report,
- a weather check for their village on the loss date,
- a printable claim packet with their details, the photo's time and GPS, the weather
  record, and a log of every check the agent ran,
- a calendar reminder that alerts them 12 hours and 3 hours before the deadline.

## How it is built

```
browser -> CloudFront -> S3 (web app)
                    \-> /api/* -> Lambda -> AgentCore Runtime (Strands agent)
                                    |              |-> Bedrock (Amazon Nova Pro)
                                    |              |-> Open-Meteo weather archive
                                    |-> Amazon Transcribe (voice notes)
                                    \-> S3 (photos, voice, packets) + DynamoDB (claims)
```

The agent is written with the **Strands Agents SDK** and runs on **Amazon Bedrock
AgentCore Runtime**. The model is **Amazon Nova Pro**. The whole thing is one CDK stack
deployed with the AgentCore CLI, all pay-per-use, with an AWS Budget alarm at $10 a month.

### Skills: one per cause of loss

Each cause of loss needs different evidence. Hail damage needs a close shot of broken
stems; a flood needs a photo showing standing water; a field fire needs the burnt patch
and its edge. Instead of one huge prompt, each cause is a `SKILL.md` file loaded with
Strands `AgentSkills`: hailstorm, heavy rain and flooding, landslide, field fire, and
post-harvest loss. The agent turns on the right skill once it knows the cause, so the
base prompt stays short.

### Tools

| Tool | What it does |
|---|---|
| `save_claim_details` | Saves name, village, crop, cause, area, date. Crop and cause come from fixed lists, so "dhaan" lands as paddy, not something made up. |
| `inspect_photo` | Reads the photo's EXIF time and GPS, falls back to the phone's location, and writes a short visual note. |
| `check_weather` | Pulls rain, thunderstorm codes and wind gusts near the field for the loss date and the day before. |
| `deadline_status` | Hours left in the 72-hour window. |
| `generate_claim_packet` | Builds the HTML packet in S3. |

### Rules the model cannot talk its way around

This was the most important design choice. A farmer's claim should not depend on a
language model following instructions on a good day. So the hard rules live in code:

- **Steering.** A Strands `SteeringHandler` (`PacketGate`) sits in front of
  `generate_claim_packet`. If anything is missing (a detail, a photo with location, a
  photo taken *after* the loss, the weather check) the call is blocked and the agent is
  told what to ask for next.
- **The farmer decides, not the model.** If the weather record shows no storm, the
  packet stays blocked until the farmer presses **File anyway** in the app. The model has
  no way to set that flag. The packet then asks for a field inspection, because weather
  grids are about 10 km wide and can miss a hailstorm that hit one village. The agent
  never rejects a farmer.
- **Audit trail.** A Strands `HookProvider` logs every tool call, and the log is printed
  in the packet, so an insurance officer can see what was checked and when.
- **No money talk.** The agent never promises an amount or approval. The insurer decides.

### Language

Farmers write in all three styles, often mixed. The app has an English / हिन्दी /
Hinglish switch for the interface, and the agent answers in whatever the farmer writes.
A small detector in the service looks at the script and common words of each message and
adds a hint, which stopped Nova from answering an English message in Devanagari.

### Voice

Many farmers would rather speak than type. The browser's built-in speech recognition
does not work in Brave or Firefox, so the app records a short clip, uploads it to S3 with
a presigned link, and **Amazon Transcribe** turns it into text (hi-IN or en-IN). The
farmer sees the text before sending it. A 20-second note costs well under one cent.

### Photos never pass through the server

Photos go from the phone straight to S3 with a presigned POST (10 MB cap). The Lambda only
hands out upload links and forwards chat turns, so it stays small and fast. The claim id
doubles as the AgentCore session id, so every turn of one claim lands in the same session.

## Testing it

Unit tests cover the checklist, deadline maths, EXIF reading and the language detector.
On top of that there is an eval suite (`agent/evals/run_evals.py`) with 14 scripted
claims run against the real model, with fake weather and photo results so the outcome is
known in advance. Each case checks:

- whether a packet should be made or blocked (old photo, no photo, dry weather, a prompt
  injection asking to "skip the weather check"),
- whether crop, cause, area and date were saved correctly ("5 bigha" must not become
  5 acres; "parson" must become the right date),
- whether the reply is in the farmer's language,
- that there are no money promises and no internal words like tool names.

The first full run passed 12 of 14. The failures were real: the agent kept asking for the
exact hour of a loss instead of making the packet, and it sometimes leaked internal photo
ids like "P1" into replies. After fixing those (time of day became optional, with the
safe default of midnight, and a small filter removes photo ids), the latest run passes
all 14 cases and 96 of 96 checks. The eval also caught two bugs in itself: it counted
"I can't promise any amount" as a money promise.

## What I learned

- **Put the rules in code, not in the prompt.** Early on the model would happily make a
  packet with a photo from last month if the farmer pushed. Steering fixed that in one
  place.
- **Fixed lists beat free text.** Letting the model write any crop name gave "pigeon_pea"
  for "paddy". A fixed list with local names in the tool description fixed it.
- **Don't let a model judge damage from one photo.** Every model I tried got some photos
  wrong. The visual note goes in the packet as a note, and the farmer is never told
  "your photo shows no damage".
- **Tell the model the next step in the tool result.** Once every check passed, Nova
  sometimes asked "shall I make the packet?" and sometimes said the packet was ready
  without making it. A `next_step` line in the tool results ("the packet has NOT been
  made yet, call generate_claim_packet now") made it consistent.
- **Keep long URLs away from the model.** A presigned S3 link in a tool result made Nova
  echo it back and hit the token limit. The tool now just says the packet is ready, and
  the app shows the button.

## What's next

- WhatsApp as a channel, since that is where farmers already are.
- More languages (Marathi, Telugu, Odia) through the same skills.
- Send the packet straight to the insurer's intimation API where one exists.

Built solo for the AWS Builder Center "Strands SDK: Workshop to Ship" hackathon.
