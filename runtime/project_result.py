"""Compatibility import for the canonical project execution result.

The canonical ``ProjectResult`` lives in ``core.project_result``.  Runtime
callers historically imported it from this module, so keep this module as a
single compatibility boundary rather than maintaining a second, structurally
incompatible result type.  In particular, persistence type checks must see the
same class regardless of which public import path a caller uses.
"""

from core.project_result import ProjectResult

__all__ = ["ProjectResult"]
