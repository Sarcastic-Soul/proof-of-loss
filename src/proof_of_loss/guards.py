"""Steering and hooks that keep the agent honest.

PacketGate: blocks generate_claim_packet until the checklist passes, and tells
the agent exactly what is missing. It reads the stored claim, not the model's
memory, so the model cannot talk its way past it.

AuditTrail: records every tool call on the claim so the packet can show how it
was made.
"""

from datetime import datetime

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
from strands.vended_plugins.steering import Guide, Proceed, SteeringHandler, ToolSteeringAction

from . import config
from .checklist import gate_problems
from .tools import ClaimContext


class PacketGate(SteeringHandler):
    name = "packet-gate"

    def __init__(self, ctx: ClaimContext):
        super().__init__()
        self.ctx = ctx

    async def steer_before_tool(self, *, agent, tool_use, **kwargs) -> ToolSteeringAction:
        if tool_use.get("name") != "generate_claim_packet":
            return Proceed(reason="not a packet request")
        problems = gate_problems(self.ctx.load())
        if problems:
            return Guide(reason="The claim packet cannot be made yet. Fix these first, asking "
                                "the farmer where needed: " + "; ".join(problems) + ".")
        return Proceed(reason="checklist passed")


class AuditTrail(HookProvider):
    def __init__(self, ctx: ClaimContext):
        self.ctx = ctx

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(AfterToolCallEvent, self.record)

    def record(self, event: AfterToolCallEvent) -> None:
        text = " ".join(c.get("text", "") for c in event.result.get("content", []))
        status = event.result.get("status", "unknown")
        if "Tool call cancelled" in text:
            status = "blocked by checklist"
        elif '"error"' in text or "'error'" in text:
            status = "error"
        claim = self.ctx.load()
        claim["audit"].append({
            "at": datetime.now(config.IST).isoformat(timespec="seconds"),
            "tool": event.tool_use["name"],
            "status": status,
        })
        self.ctx.save(claim)
