"""Retired compatibility import for the research-only integration harness.

Production decisions use :mod:`hermes_escape_top.pipeline`. New research code
must import :mod:`hermes_escape_top.core.research.integration_pipeline` so the
two execution models cannot be confused during review.
"""

from .research.integration_pipeline import PipelineResult, score_pipeline


RETIRED_COMPATIBILITY_SHIM = True

__all__ = ["PipelineResult", "score_pipeline"]
