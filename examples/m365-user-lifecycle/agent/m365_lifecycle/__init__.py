"""Reference Microsoft 365 joiner and leaver agent, governed end to end by Behavry.

PSA request -> signature check -> Claude reads the form into fixed fields
(through Behavry's Anthropic proxy) -> the MSP's client catalogue turns those
fields into a plan -> each step runs through Behavry's MCP gateway, where policy
lets containment through and holds every grant for a person -> the plan and
every outcome are written on the PSA ticket. One request, one Decision Trace.
"""

__version__ = "0.1.0"
