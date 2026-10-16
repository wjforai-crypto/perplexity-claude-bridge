"""Run offline suites in separate processes to isolate upstream globals."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
for test in ('test_anthropic_bridge.py', 'check_routing.py', 'test_portability.py'):
    subprocess.run([sys.executable, str(root / test)], check=True,
                   env=dict(os.environ, PYTHONIOENCODING='utf-8'))
print('All offline suites passed. No account or network requests are required.')
