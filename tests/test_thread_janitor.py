import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from computer_backend import ask_computer
from test_computer_backend import data, response
from thread_janitor import DELETE_THREAD, DELETE_TIMEOUT, ThreadJanitor, delete_thread


class DeleteTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ, {'PWM_THREAD_CLEANUP':'1'})
        env.start();self.addCleanup(env.stop)
        self.session=MagicMock()
        self.reply=self.session.delete.return_value
        self.reply.status_code=200
        self.reply.json.return_value={'failed':[]}

    def test_explicit_success_and_exact_single_thread_body(self):
        for body in ({'status':'success','failed':None}, {'success':True}, {'failed':[]}):
            with self.subTest(body=body):
                self.reply.json.return_value=body
                with self.assertLogs('thread_janitor',level='INFO') as logs:
                    self.assertTrue(delete_thread(self.session,'our-task','rw-fixture'))
                self.assertIn('removed self-created thread',logs.output[0])
        self.session.delete.assert_called_with(DELETE_THREAD,json={
            'entry_uuids':['our-task'],'context_uuids':[], 'read_write_token':'rw-fixture'},
            timeout=DELETE_TIMEOUT)
        self.assertEqual(self.reply.close.call_count,3)

    def test_failures_and_unknown_json_never_log_success(self):
        for body in ({'success':False,'error':'denied'}, {'failed':['our-task']},
                     {'success':True,'status':'error'}, {'status':'success','failed':['our-task']},
                     {'status':'success','success':False}, {'error_code':'denied'},
                     {}, {'status':'ok'}, [], None):
            with self.subTest(body=body):
                self.reply.json.return_value=body
                with self.assertLogs('thread_janitor',level='WARNING') as logs:
                    self.assertFalse(delete_thread(self.session,'our-task'))
                self.assertNotIn('removed self-created thread',' '.join(logs.output))

    def test_non_json_response_is_unconfirmed(self):
        self.reply.json.side_effect=ValueError('HTML')
        with self.assertLogs('thread_janitor',level='WARNING') as logs:
            self.assertFalse(delete_thread(self.session,'our-task'))
        self.assertIn('unconfirmed',' '.join(logs.output))
        self.reply.close.assert_called_once()

    def test_http_and_network_failure_are_swallowed(self):
        self.reply.status_code=403
        self.assertFalse(delete_thread(self.session,'our-task'))
        self.reply.close.assert_called_once()
        self.session.delete.side_effect=OSError('offline')
        self.assertFalse(delete_thread(self.session,'our-task'))

    def test_disabled_or_missing_id_does_not_delete(self):
        self.assertFalse(delete_thread(self.session,None))
        with patch.dict(os.environ,{'PWM_THREAD_CLEANUP':'0'}):
            self.assertFalse(delete_thread(self.session,'our-task'))
        self.session.delete.assert_not_called()


class QueueTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ, {'PWM_THREAD_CLEANUP':'1'})
        env.start();self.addCleanup(env.stop)

    def test_slow_cleanup_does_not_hold_answer_and_uses_own_session(self):
        entered,release=threading.Event(),threading.Event()
        cleanup_session=MagicMock()
        cleanup_session.__enter__.return_value=cleanup_session
        def slow_delete(*args,**kwargs):
            entered.set()
            if not release.wait(5):raise RuntimeError('probe not released')
            return MagicMock(status_code=200,json=lambda:{'success':True})
        cleanup_session.delete.side_effect=slow_delete
        factory=MagicMock(return_value=cleanup_session)
        janitor=ThreadJanitor(factory)
        active=MagicMock();active.__enter__.return_value=active
        active.get.return_value.status_code=200
        active.get.return_value.json.return_value={'can_use_computer':True}
        event=data();event['read_write_token']='rw-fixture'
        active.post.return_value=response([event])
        answers=[];errors=[];done=threading.Event()
        def request():
            try:
                answers.append(ask_computer('query','pplx_asi_opus','offline-only',MagicMock(),
                                           session_factory=lambda _:active))
            except Exception as exc:errors.append(type(exc).__name__)
            finally:done.set()
        try:
            with patch('computer_backend.schedule_thread_cleanup',side_effect=janitor.submit):
                caller=threading.Thread(target=request)
                caller.start()
                self.assertTrue(entered.wait(2))
                self.assertTrue(done.wait(2),'answer waited for deletion')
                self.assertFalse(release.is_set())
                self.assertEqual(answers,['real answer']);self.assertEqual(errors,[])
                active.delete.assert_not_called()
                active.__exit__.assert_called_once()
                factory.assert_called_once_with('offline-only')
                self.assertEqual(cleanup_session.delete.call_args.kwargs['json']['read_write_token'],'rw-fixture')
        finally:
            release.set();caller.join(2);janitor.close()
        cleanup_session.__exit__.assert_called_once()

    def test_queue_overflow_is_bounded_and_shutdown_rejects_jobs(self):
        entered,release=threading.Event(),threading.Event()
        session=MagicMock();session.__enter__.return_value=session
        def delayed(*args,**kwargs):
            entered.set();release.wait(5)
            return MagicMock(status_code=200,json=lambda:{'failed':[]})
        session.delete.side_effect=delayed
        janitor=ThreadJanitor(lambda _:session,max_pending=1)
        try:
            self.assertTrue(janitor.submit('offline-only','one'))
            self.assertTrue(entered.wait(2))
            self.assertTrue(janitor.submit('offline-only','two'))
            with self.assertLogs('thread_janitor',level='WARNING'):
                self.assertFalse(janitor.submit('offline-only','three'))
            self.assertEqual(janitor._jobs.qsize(),1)
            with self.assertLogs('thread_janitor',level='WARNING'):
                janitor.close(timeout=0)
                self.assertFalse(janitor.submit('offline-only','after-close'))
        finally:
            release.set();janitor.close()
        self.assertEqual(session.delete.call_count,2)
        self.assertFalse(janitor._worker.is_alive())

    def test_session_failure_does_not_kill_worker(self):
        session=MagicMock();session.__enter__.return_value=session
        session.delete.return_value.status_code=200
        session.delete.return_value.json.return_value={'success':True}
        factory=MagicMock(side_effect=[OSError('offline'),session])
        janitor=ThreadJanitor(factory)
        try:
            self.assertTrue(janitor.submit('offline-only','one'))
            self.assertTrue(janitor.submit('offline-only','two'))
        finally:janitor.close()
        self.assertEqual(factory.call_count,2)
        session.delete.assert_called_once()
        self.assertFalse(janitor._worker.is_alive())

    def test_disabled_or_missing_id_never_starts_worker(self):
        factory=MagicMock()
        janitor=ThreadJanitor(factory)
        try:
            self.assertFalse(janitor.submit('offline-only',None))
            with patch.dict(os.environ,{'PWM_THREAD_CLEANUP':'0'}):
                self.assertFalse(janitor.submit('offline-only','one'))
            self.assertIsNone(janitor._worker)
            factory.assert_not_called()
        finally:janitor.close()


if __name__=='__main__':unittest.main(verbosity=2)
