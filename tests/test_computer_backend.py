import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from computer_backend import ask_computer,ComputerError

def data(status='COMPLETED',model='pplx_asi_opus',answer='real answer'):
    return {'status':status,'mode':'ASI','display_model':model,'backend_uuid':'task-one',
            'blocks':[{'intended_usage':'workflow_root','workflow_block':{'steps':[{'items':[{'payload':{'text_payload':{'text':answer}}}]}]}}]}
def response(events=(),status=200):
    obj=MagicMock(status_code=status)
    obj.iter_lines.return_value=iter(('data: '+json.dumps(e)).encode() for e in events)
    return obj

class ComputerTests(unittest.TestCase):
    def run_query(self,responses,access=None,**kwargs):
        self.session=MagicMock()
        self.session.__enter__.return_value=self.session
        self.session.get.return_value.status_code=200
        self.session.get.return_value.json.return_value=access or {'can_use_computer':True}
        self.session.post.side_effect=responses
        self.uploader=MagicMock()
        self.uploader._validate_files.return_value=['fileinfo']
        self.uploader._upload_file.return_value='https://fixture.invalid/uploaded'
        return ask_computer('query','pplx_asi_opus','offline-only',self.uploader,
                            session_factory=lambda _:self.session,**kwargs)
    def test_final_workflow_answer_and_attachments(self):
        self.assertEqual(self.run_query([response([data()])],files=['fixture.png']),'real answer')
        params=self.session.post.call_args.kwargs['json']['params']
        self.assertEqual(params['model_preference'],'pplx_asi_opus')
        self.assertEqual(params['attachments'],['https://fixture.invalid/uploaded'])
    def test_reconnect_same_task_without_resubmit(self):
        self.assertEqual(self.run_query([response([data('PENDING',answer='ignore partial')]),response([data()])]),'real answer')
        self.assertEqual(self.session.post.call_count,2)
        self.assertTrue(self.session.post.call_args.args[0].endswith('/reconnect/task-one'))
        self.assertEqual(self.session.post.call_args.kwargs['json'],{'reconnectInitialSnapshot':True})
    def test_quota_error_prevents_upload_and_task(self):
        with self.assertRaises(ComputerError) as caught:
            self.run_query([],access={'can_use_computer':True,'is_out_of_credits':True},files=['fixture.png'])
        self.assertEqual(caught.exception.status,429)
        self.uploader._upload_file.assert_not_called()
        self.session.post.assert_not_called()
    def test_model_mismatch_is_rejected(self):
        with self.assertRaises(ComputerError) as caught:self.run_query([response([data(model='pplx_asi_sonnet')])])
        self.assertEqual(caught.exception.code,'computer_model_mismatch')
    def test_unknown_submit_outcome_never_retried(self):
        with self.assertRaises(ComputerError) as caught:self.run_query([OSError('connection dropped')])
        self.assertEqual(caught.exception.code,'computer_submission_unknown')
        self.assertEqual(self.session.post.call_count,1)
    def test_client_cancel_prevents_submission(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(ComputerError) as caught:self.run_query([],cancel=cancel)
        self.assertEqual(caught.exception.code,'computer_cancelled')
        self.session.post.assert_not_called()
    def test_exhausted_reconnects_are_bounded(self):
        with self.assertRaises(ComputerError) as caught:self.run_query([response([data('PENDING')]) for _ in range(6)])
        self.assertEqual(caught.exception.status,504)
        self.assertEqual(self.session.post.call_count,6)

if __name__=='__main__':unittest.main(verbosity=2)
