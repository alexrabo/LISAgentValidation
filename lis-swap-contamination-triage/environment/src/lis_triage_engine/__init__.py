"""
lis-triage-engine — LIS specimen triage scoring engine.

Public API:
    run_triage(batch, workflow) -> dict
        Importable entry point for lims_server.py.
        Accepts dicts, returns decisions keyed by specimen_id.
"""
from .triage import run_triage, main  # noqa: F401

__all__ = ["run_triage"]
__version__ = "1.0.0"
