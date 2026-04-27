"""Models for this bounded context.

Cross-context model imports are forbidden (see ARCHITECTURE.md). Other contexts
should call this context's ``services`` module, never import these models directly.
"""

from django.db import models  # noqa: F401  (re-exported for migrations discovery)
