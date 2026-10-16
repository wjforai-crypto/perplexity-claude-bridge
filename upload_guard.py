"""Recognize upload quotas and reuse unchanged, already uploaded attachments.

URLs stay in bounded process memory, partitioned by authenticated account.
"""
from collections import OrderedDict
import hashlib
from pathlib import Path
import threading
import time

from perplexity_web_mcp.constants import ENDPOINT_UPLOAD
from perplexity_web_mcp.core import Conversation
from perplexity_web_mcp.exceptions import FileUploadError
from perplexity_web_mcp.http import HTTPClient

CACHE_TTL = 900
CACHE_SIZE = 128
COOLDOWN = 60
_cache = OrderedDict()
_blocked = {}
_lock = threading.RLock()
_fresh_upload = threading.local()


def force_fresh_upload():
    """Bypass the upload-URL cache within the block.

    The ASI backend does not re-bind a previously used upload URL to a new
    task; Conversation uses __slots__, so the flag lives in a thread-local
    instead of an instance attribute.
    """
    class _Scope:
        def __enter__(self):
            self.previous = getattr(_fresh_upload, 'enabled', False)
            _fresh_upload.enabled = True
        def __exit__(self, *exc):
            _fresh_upload.enabled = self.previous
    return _Scope()


class UploadRateLimitError(FileUploadError):
    retry_after = COOLDOWN

    def __init__(self, path='attachment'):
        super().__init__(path, 'Perplexity file uploads are currently rate limited. The reset time is not supplied by the service. Do not repeatedly reupload this file; continue with local text or sampled images where supported.')


def account_key(http):
    return hashlib.sha256(http._session_token.encode()).digest()


def upload_bucket(info):
    return 'image' if info.is_image else 'document'


def clear_state():
    with _lock:
        _cache.clear()
        _blocked.clear()


def check_upload_response(http, endpoint, request_body, response):
    if endpoint != ENDPOINT_UPLOAD:
        return
    data = response.json()
    request_files = (request_body or {}).get('files', {})
    for identifier, result in data.get('results', {}).items():
        if result.get('rate_limited') is True:
            request = request_files.get(identifier, {})
            bucket = 'image' if request.get('force_image') else 'document'
            with _lock:
                _blocked[(account_key(http), bucket)] = time.monotonic() + COOLDOWN
            raise UploadRateLimitError(Path(request.get('filename', 'attachment')).name)


def cached_upload(conversation, info, upload):
    account = account_key(conversation._http)
    key = (account, info.mimetype, Path(info.path).name, hashlib.sha256(Path(info.path).read_bytes()).digest())
    now = time.monotonic()
    fresh = getattr(_fresh_upload, 'enabled', False)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now and not fresh:
            _cache.move_to_end(key)
            return cached[1]
        if cached:
            del _cache[key]
        if _blocked.get((account, upload_bucket(info)), 0) > now:
            raise UploadRateLimitError(Path(info.path).name)
    result = upload(conversation, info)
    with _lock:
        _cache[key] = (time.monotonic() + CACHE_TTL, result)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def install_upload_guard():
    if getattr(Conversation, '_local_upload_guard_installed', False):
        return
    original_post = HTTPClient.post
    original_upload = Conversation._upload_file

    def guarded_post(self, endpoint, *args, **kwargs):
        response = original_post(self, endpoint, *args, **kwargs)
        check_upload_response(self, endpoint, kwargs.get('json'), response)
        return response

    def guarded_upload(self, info):
        return cached_upload(self, info, original_upload)

    HTTPClient.post = guarded_post
    Conversation._upload_file = guarded_upload
    Conversation._local_upload_guard_installed = True
