"""Shared Rich console instance."""
import sys
from rich.console import Console

# On Windows, stdout defaults to cp1250 which can't encode Unicode symbols (✓, →, etc.).
# reconfigure() changes encoding in-place without replacing the file object,
# so pytest's capture mechanism still works.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, IOError):
        pass

console = Console()
