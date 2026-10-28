"""AgentCore Runtime entrypoint.

Payload: {"claim_id": str, "message": str, "photos": [...], "file_anyway": bool}
"""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .service import handle_turn
from .store import default_stores

app = BedrockAgentCoreApp()
CLAIMS, BLOBS = default_stores()


@app.entrypoint
def invoke(payload: dict, context) -> dict:
    claim_id = payload.get("claim_id") or context.session_id
    if not claim_id:
        return {"error": "claim_id or runtime session id required"}
    return handle_turn(
        claim_id=claim_id,
        message=payload.get("message", ""),
        photos=payload.get("photos"),
        file_anyway=bool(payload.get("file_anyway")),
        claims=CLAIMS,
        blobs=BLOBS,
    )


if __name__ == "__main__":
    app.run()
