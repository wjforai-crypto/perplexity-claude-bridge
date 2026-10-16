"""Installation-relative paths. Tests can isolate state with PWM_PRIVATE_DIR."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get('PWM_PRIVATE_DIR', str(ROOT / 'private'))).expanduser().resolve()
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
