"""Create a protected state directory and local API key without exposing it."""
import csv
import io
import os
import secrets
import subprocess

from local_config import PRIVATE


def initialize():
    if os.name == 'nt':
        account = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                 capture_output=True, text=True, check=True)
        sid = next(csv.reader(io.StringIO(account.stdout.strip())))[1]
        subprocess.run(['icacls', str(PRIVATE), '/inheritance:r', '/grant:r',
                        f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                       capture_output=True, check=True)
    else:
        PRIVATE.chmod(0o700)
    key_path = PRIVATE / 'api-key.txt'
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not key_path.read_text(encoding='utf-8').strip():
            raise RuntimeError('Existing API key is empty; restore it or remove that empty file and initialize again.')
    else:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(secrets.token_urlsafe(32) + '\n')
    print('Local state initialized. API key saved in private/api-key.txt (not displayed).')


if __name__ == '__main__':
    initialize()
