"""Reference Meraki alert triage agent, governed end to end by Behavry.

Meraki webhook -> noise gate -> Halo lookup (through your MCP gateway) -> Claude
triage (through Behavry's Anthropic proxy) -> Halo note, assignment, and an
approval-gated remediation request. Every model and tool call carries the
alert's run label, so one alert reads as one Decision Trace.
"""

__version__ = "0.1.0"
