import sys
from pathlib import Path

# Make src-layout importable without an editable install.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
