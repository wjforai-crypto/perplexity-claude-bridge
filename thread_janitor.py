"""Cleanup for threads that this proxy itself created on the Perplexity web app.

The Computer/ASI transport creates one new web thread per application turn.
Those threads pile up in the user's History sidebar. This module deletes only
the thread whose backend_uuid was captured during the current turn — never
anything else on the account. Cleanup is best-effort: any failure is logged
and swallowed. A bounded background queue uses separate sessions so network
cleanup cannot hold the application response or its request-concurrency slot.

Endpoint was recovered from the official web frontend (sidebar delete action):
DELETE /rest/thread  {"entry_uuids":[...], "context_uuids":[], "read_write_token":...}

Set PWM_THREAD_CLEANUP=0 to disable cleanup entirely.
"""
import atexit
import logging
import os
import queue
import threading

from perplexity_web_mcp.rate_limits import _create_session

BASE = 'https://www.perplexity.ai'
DELETE_THREAD = BASE + '/rest/thread'
DELETE_TIMEOUT = 10

_log = logging.getLogger(__name__)


def cleanup_enabled():
    return os.environ.get('PWM_THREAD_CLEANUP', '1') != '0'


def delete_thread(session, entry_uuid, read_write_token=''):
    """Delete exactly one thread we created this turn. Returns True on success.

    Never raises: cleanup failure must not affect the caller's result.
    """
    if not cleanup_enabled():
        return False
    if not entry_uuid:
        return False
    response = None
    try:
        body = {'entry_uuids': [entry_uuid], 'context_uuids': [],
                'read_write_token': read_write_token or ''}
        response = session.delete(DELETE_THREAD, json=body, timeout=DELETE_TIMEOUT)
        if response.status_code != 200:
            _log.warning('thread janitor: delete of %s returned HTTP %s',
                         entry_uuid, response.status_code)
            return False
        try:
            result = response.json()
        except (ValueError, TypeError):
            _log.warning('thread janitor: deletion unconfirmed for %s: non-JSON response', entry_uuid)
            return False
        if not isinstance(result, dict):
            _log.warning('thread janitor: deletion unconfirmed for %s: unexpected response type', entry_uuid)
            return False
        if (result.get('error') or result.get('error_code') or result.get('failed')
                or result.get('success') is False
                or str(result.get('status', '')).lower() in ('error', 'failed', 'failure')):
            _log.warning('thread janitor: delete of %s reported failure', entry_uuid)
            return False
        # Do not infer success from HTTP 200 or from a missing failure field.
        # Unrecognized response shapes remain unconfirmed until verified live.
        # Observed live: {"status": "success", "failed": null}.
        confirmed = result.get('status') == 'success' or result.get('success') is True or (
            'failed' in result and result['failed'] == [])
        if not confirmed:
            _log.warning('thread janitor: deletion unconfirmed for %s: no affirmative result', entry_uuid)
            return False
        _log.info('thread janitor: removed self-created thread %s', entry_uuid)
        return True
    except Exception as exc:
        _log.warning('thread janitor: delete of %s failed: %s',
                     entry_uuid, type(exc).__name__)
        return False
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


class ThreadJanitor:
    """One daemon worker, at most 64 queued jobs, and one session per deletion.

    Submission never waits for network IO. Overflow is logged and skipped.
    Normal interpreter exit allows two seconds to drain; forced termination
    can leave jobs unfinished. No jobs or credentials are persisted to disk.
    """

    def __init__(self, session_factory=None, max_pending=64):
        self._session_factory = session_factory or _create_session
        self._jobs = queue.Queue(maxsize=max_pending)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._worker = None

    def submit(self, token, entry_uuid, read_write_token=''):
        if not entry_uuid or not cleanup_enabled():
            return False
        try:
            with self._lock:
                if self._closed.is_set():
                    _log.warning('thread janitor: shutdown; cleanup skipped for %s', entry_uuid)
                    return False
                if self._worker is None or not self._worker.is_alive():
                    worker = threading.Thread(target=self._run, name='thread-janitor', daemon=True)
                    worker.start()
                    self._worker = worker
                self._jobs.put_nowait((token, entry_uuid, read_write_token))
            return True
        except queue.Full:
            _log.warning('thread janitor: queue full; cleanup skipped for %s', entry_uuid)
        except Exception as exc:
            _log.warning('thread janitor: could not schedule cleanup for %s: %s',
                         entry_uuid, type(exc).__name__)
        return False

    def _run(self):
        while True:
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                if self._closed.is_set():
                    return
                continue
            try:
                token, entry_uuid, rw_token = job
                with self._session_factory(token) as session:
                    delete_thread(session, entry_uuid, rw_token)
            except Exception as exc:
                _log.warning('thread janitor: cleanup session failed for %s: %s',
                             job[1], type(exc).__name__)
            finally:
                self._jobs.task_done()
                # Release credentials even while the worker is idle.
                del job
                token = rw_token = session = None

    def close(self, timeout=2):
        with self._lock:
            self._closed.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=max(0, timeout))
            if worker.is_alive():
                _log.warning('thread janitor: shutdown budget elapsed; cleanup may remain unfinished')


_janitor = ThreadJanitor()
atexit.register(_janitor.close)


def schedule_thread_cleanup(token, entry_uuid, read_write_token=''):
    return _janitor.submit(token, entry_uuid, read_write_token)
