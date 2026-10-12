"""Make the standalone proto generator importable from the repository test tree.

``proto_gen`` is not a workspace package, so nothing puts ``scripts/`` on the
path the way ``just proto-gen`` does for the CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
