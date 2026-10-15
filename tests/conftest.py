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

#: Server modules whose configuration is read at import time (the data root).
#: Tests that need a different configuration drop these and re-import, so they
#: must all be listed here.
SERVER_MODULES = (
    "server.courses", "server.bank", "server.recycle", "server.blocks",
    "server.latex", "server.papers", "server.appdb", "server.auth",
    "server.appapi", "server.main",
)


def reload_server_modules() -> None:
    """Force a genuine re-import of the server modules.

    Emptying ``sys.modules`` is not enough on its own: the ``server`` package
    keeps an attribute pointing at whichever module was imported first, and
    ``from server import bank`` hands that stale module straight back.  The
    attribute has to go too, or a test silently reads the previous test's data.
    """
    import server as server_package

    for name in SERVER_MODULES:
        sys.modules.pop(name, None)
        attribute = name.split(".", 1)[1]
        if hasattr(server_package, attribute):
            delattr(server_package, attribute)
