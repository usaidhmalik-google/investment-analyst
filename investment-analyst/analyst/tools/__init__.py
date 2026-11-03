"""ADK tool layer: deterministic data tools the specialist agents can call.

Tool functions are registered natively in ADK; their parameter types become the
function-calling schema and their return payloads are Pydantic models dumped to
JSON-safe dicts. Every successful call also records an *evidence* entry in session
state, keyed by a citation id, which the Financial Analyst must cite and which the
post-generation fact checker verifies against.
"""
