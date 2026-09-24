"""Central subagent roster + harness adapters (Cursor, OpenCode)."""

from mailroom_sandbox.subagents.roster import SubagentEntry, load_roster
from mailroom_sandbox.subagents.sync import sync_harness

__all__ = ["SubagentEntry", "load_roster", "sync_harness"]
