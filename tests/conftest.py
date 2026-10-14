"""Make the project importable from the tests directory.

``tests/`` has no ``__init__.py``, so pytest inserts *this* directory on
``sys.path`` and ``import server`` would fail.  Adding the repository root keeps
``python -m pytest`` and a bare ``pytest`` equivalent.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
