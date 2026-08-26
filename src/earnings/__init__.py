"""Auditable earnings-call transcript analysis POC.

Deterministic pipeline: ingest -> sanitise -> segment -> hash/manifest -> (agent
extracts quote-anchored claims via a skill) -> validate -> calculate -> signal card.
"""

__version__ = "0.1.0"
