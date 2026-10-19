import sys
from pathlib import Path

# Allows both ``python -m uav_mcp`` and ``python path/to/uav_mcp`` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uav_mcp.server import main  # noqa: E402

main()
