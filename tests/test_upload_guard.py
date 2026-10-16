import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import upload_guard as guard


class UploadGuardTests(unittest.TestCase):
    def setUp(self):
        guard.clear_state()
        self.temp=tempfile.TemporaryDirectory()
        self.path=pathlib.Path(self.temp.name)/'sample.png'
        self.path.write_bytes(b'synthetic fixture')
        self.http=SimpleNamespace(_session_token='offline-account-A')
        self.conv=SimpleNamespace(_http=self.http)
        self.info=SimpleNamespace(path=str(self.path),mimetype='image/png',is_image=True)
    def tearDown(self):
        self.temp.cleanup()
        guard.clear_state()
    def limit_documents(self):
        response=Mock()
        response.json.return_value={'results':{'id':{'s3_bucket_url':None,'s3_object_url':None,'fields':None,'rate_limited':True,'file_uuid':None,'error':None}}}
        with self.assertRaises(guard.UploadRateLimitError):
            guard.check_upload_response(self.http,guard.ENDPOINT_UPLOAD,{'files':{'id':{'filename':'context.txt','force_image':False}}},response)
    def test_exact_rate_limited_payload_and_cooldown(self):
        self.limit_documents()
        self.info.is_image=False;self.info.mimetype='text/plain'
        upload=Mock()
        with self.assertRaises(guard.UploadRateLimitError):guard.cached_upload(self.conv,self.info,upload)
        upload.assert_not_called()
    def test_document_limit_does_not_block_images(self):
        self.limit_documents()
        upload=Mock(return_value='already-authenticated-upload-url')
        self.assertEqual(guard.cached_upload(self.conv,self.info,upload),'already-authenticated-upload-url')
        upload.assert_called_once()
    def test_cache_scoped_to_account_content_and_expiry(self):
        upload=Mock(return_value='already-authenticated-upload-url')
        guard.cached_upload(self.conv,self.info,upload)
        guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,1)
        self.path.write_bytes(b'changed content')
        guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,2)
        other=SimpleNamespace(_http=SimpleNamespace(_session_token='offline-account-B'))
        guard.cached_upload(other,self.info,upload)
        self.assertEqual(upload.call_count,3)
        with patch.object(guard.time,'monotonic',return_value=guard.time.monotonic()+guard.CACHE_TTL+1):
            guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,4)
    def test_failed_upload_is_never_cached(self):
        upload=Mock(side_effect=RuntimeError('failure'))
        for _ in range(2):
            with self.assertRaises(RuntimeError):guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,2)
    def test_forced_fresh_upload_bypasses_url_cache(self):
        # The ASI backend does not re-bind a previously used upload URL to a new
        # task; reusing one yields an attachment record without content. Callers
        # on that route force fresh uploads via the thread-local scope because
        # Conversation instances use __slots__.
        upload=Mock(return_value='fresh-url')
        guard.cached_upload(self.conv,self.info,upload)
        with guard.force_fresh_upload():
            guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,2)
        with guard.force_fresh_upload():
            self.assertEqual(guard.cached_upload(self.conv,self.info,upload),'fresh-url')
        self.assertEqual(upload.call_count,3)
        # Scope exit restores caching.
        guard.cached_upload(self.conv,self.info,upload)
        self.assertEqual(upload.call_count,3)

if __name__=='__main__':unittest.main()
