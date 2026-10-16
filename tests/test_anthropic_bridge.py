import base64,json,pathlib,sys,unittest,os,tempfile,atexit
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
_private = tempfile.TemporaryDirectory(prefix='bridge-offline-')
atexit.register(_private.cleanup)
os.environ['PWM_PRIVATE_DIR'] = _private.name
(pathlib.Path(_private.name)/'api-key.txt').write_text('offline-fixture-key', encoding='utf-8')
import pwm_local
from anthropic_bridge import parse_response,BridgeProtocolError
from fastapi.testclient import TestClient
s=pwm_local.configure_api()
ROOT=pathlib.Path(__file__).resolve().parent
TOOL={'name':'Read','description':'Read local file','input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path'],'additionalProperties':False}}
KEY='offline-fixture-key'

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.answers=[];self.captured=[]
        self.computer_models=[]
        def computer(query,model,token,uploader,files,cancel):
            self.computer_models.append(model)
            uploader.ask(query,files=files)
            return uploader.answer
        def fresh(*a,**k):
            obj=MagicMock()
            def create(*a,**k):
                conversation=MagicMock()
                def ask(query,**kw):
                    self.captured.append({'query':query,'files':[(str(p),pathlib.Path(p).read_bytes()) for p in kw.get('files') or []]})
                    conversation.answer=self.answers.pop(0) if self.answers else 'OK'
                conversation.ask.side_effect=ask
                return conversation
            obj.create_conversation.side_effect=create
            return obj
        self.patches=[patch.object(s.ServerConfig,'from_env',return_value=s.ServerConfig(session_token='offline-only',api_key=KEY)),patch.object(s,'Perplexity',side_effect=fresh),patch.object(s,'MIN_REQUEST_INTERVAL',0),patch('anthropic_bridge.ask_computer',side_effect=computer)]
        for p in self.patches:p.start()
        self.client=TestClient(s.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in reversed(self.patches):p.stop()
    def post(self,content='hello',**kwargs):
        data={'model':'claude-opus-5-5','max_tokens':100,'messages':[{'role':'user','content':content}],**kwargs}
        return self.client.post('/v1/messages',headers={'Authorization':'Bearer '+KEY},json=data)
    def test_plain_text_and_no_files(self):
        r=self.post();self.assertEqual(r.status_code,200);self.assertEqual(r.json()['content'][0]['text'],'OK');self.assertEqual(self.captured[0]['files'],[])
    def test_opus_uses_computer_and_sonnet_keeps_search(self):
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.computer_models,['pplx_asi_opus'])
        self.assertEqual(self.post(model='claude-sonnet-5-5').status_code,200)
        self.assertEqual(self.computer_models,['pplx_asi_opus'])
    def test_long_chat_does_not_require_document_upload_quota(self):
        self.answers=[json.dumps({'text':'ready','tool_calls':[]})]
        messages=[{'role':'user','content':'OLD_CONTEXT '+('history '*10000)}, {'role':'user','content':'CURRENT_TASK_749'}]
        r=self.post(messages=messages,tools=[TOOL],system='PRESERVE_CLIENT_RULES')
        self.assertEqual(r.status_code,200)
        captured=self.captured[0]
        self.assertEqual(len(captured['files']),0, 'Long chats must not reupload a document every turn')
        self.assertLessEqual(len(captured['query']),28000)
        self.assertIn('PRESERVE_CLIENT_RULES',captured['query'])
        self.assertIn('CURRENT_TASK_749',captured['query'])
        self.assertIn('local_context',captured['query'])
    def test_text_document_preserved(self):
        r=self.post([{'type':'document','source':{'type':'text','media_type':'text/plain','data':'DOC-SECRET-438'}}])
        self.assertEqual(r.status_code,200);self.assertIn('DOC-SECRET-438',self.captured[0]['query'])
    def test_base64_text_document_preserved(self):
        r=self.post([{'type':'document','source':{'type':'base64','media_type':'text/markdown','data':base64.b64encode('文档标记'.encode()).decode()}}])
        self.assertEqual(r.status_code,200);self.assertIn('文档标记',self.captured[0]['query'])
    def test_image_passed_as_file_and_cleaned(self):
        data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        r=self.post([{'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(data).decode()}}])
        self.assertEqual(r.status_code,200);name,actual=self.captured[0]['files'][0];self.assertEqual(data,actual);self.assertFalse(pathlib.Path(name).exists())
    def test_nested_tool_result_image_and_content(self):
        data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        content=[{'type':'tool_result','tool_use_id':'toolu_123','is_error':False,'content':[{'type':'text','text':'READ-RESULT-391'},{'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(data).decode()}}]}]
        r=self.post(content);self.assertEqual(r.status_code,200);self.assertIn('READ-RESULT-391',self.captured[0]['query']);self.assertIn('toolu_123',self.captured[0]['query']);self.assertEqual(len(self.captured[0]['files']),1)
    def test_historical_images_are_local_until_reread(self):
        raw=b'historical-image-fixture'
        image={'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(raw).decode()}}
        messages=[{'role':'user','content':[image]},{'role':'assistant','content':'Past analysis'},{'role':'user','content':'Continue with text only'}]
        self.answers=[json.dumps({'text':'ready','tool_calls':[]})]
        r=self.post(messages=messages,tools=[TOOL])
        self.assertEqual(r.status_code,200)
        captured=self.captured[0]
        self.assertEqual(len(captured['files']),0)
        self.assertIn('not_uploaded_in_this_request',captured['query'])
        payload=json.loads(captured['query'].split('APPLICATION REQUEST JSON:\n')[1].split('\nEND APPLICATION REQUEST.')[0])
        reference=payload['conversation'][0]['content'][0]
        self.assertEqual(pathlib.Path(reference['file_path']).read_bytes(),raw)
        # A deliberate reread on the Computer route still cannot upload into a tool turn:
        # the ASI backend never exposes attachment bytes there, so the latest image
        # stays a local reference and the model must inspect it via the local helper.
        self.answers=[json.dumps({'text':'seen','tool_calls':[]})]
        r=self.post(messages=messages+[{'role':'user','content':[image]}],tools=[TOOL])
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(self.captured[-1]['files']),0)
        payload=json.loads(self.captured[-1]['query'].split('APPLICATION REQUEST JSON:\n')[1].split('\nEND APPLICATION REQUEST.')[0])
        reference=payload['conversation'][-1]['content'][0]
        self.assertEqual(reference['type'],'local_attachment_reference')
        self.assertEqual(pathlib.Path(reference['file_path']).read_bytes(),raw)
    def test_valid_tool_call_sse(self):
        self.answers=[json.dumps({'text':'读取测试文件','tool_calls':[{'name':'Read','input':{'file_path':'C:\\test\\示例.txt'}}]})]
        r=self.post(tools=[TOOL],stream=True)
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(events[0]['type'],'message_start');self.assertEqual(events[-1]['type'],'message_stop')
        self.assertEqual(events[-2]['delta']['stop_reason'],'tool_use')
        args=''.join(e.get('delta',{}).get('partial_json','') for e in events)
        self.assertEqual(json.loads(args)['file_path'],'C:\\test\\示例.txt')
    def test_fresh_read_image_survives_trailing_system_metadata(self):
        raw=b'fresh-read-image-fixture'
        image={'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(raw).decode()}}
        messages=[{'role':'user','content':'Inspect this image'},
                  {'role':'assistant','content':[{'type':'tool_use','id':'read_current','name':'Read','input':{'file_path':'sheet.jpg'}}]},
                  {'role':'user','content':[{'type':'tool_result','tool_use_id':'read_current','content':[image]}]},
                  {'role':'system','content':'<total_tokens>100000 tokens left</total_tokens>'}]
        self.answers=[json.dumps({'text':'seen','tool_calls':[]})]
        r=self.post(messages=messages,tools=[TOOL])
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(self.captured[-1]['files']),0,'Computer tool turns never expose attachment bytes')
        payload=json.loads(self.captured[-1]['query'].split('APPLICATION REQUEST JSON:\n')[1].split('\nEND APPLICATION REQUEST.')[0])
        reference=payload['conversation'][2]['content'][0]['content'][0]
        self.assertEqual(reference['type'],'local_attachment_reference')
        self.assertEqual(pathlib.Path(reference['file_path']).read_bytes(),raw)
    def test_invalid_tool_arguments_never_emitted(self):
        self.answers=[json.dumps({'text':'','tool_calls':[{'name':'Read','input':{'file_path':42}}]})]*2
        r=self.post(tools=[TOOL]);self.assertEqual(r.status_code,502);self.assertEqual(len(self.captured),2)
    def test_unregistered_tool_never_emitted(self):
        self.answers=[json.dumps({'text':'','tool_calls':[{'name':'DestroyEverything','input':{}}]})]*2
        r=self.post(tools=[TOOL],stream=True);self.assertIn('event: error',r.text);self.assertNotIn('"type": "tool_use"',r.text)
    def test_format_repair_once(self):
        self.answers=['not JSON',json.dumps({'text':'repaired','tool_calls':[]})]
        r=self.post(tools=[TOOL]);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['content'][0]['text'],'repaired');self.assertEqual(len(self.captured),2)
    def test_unknown_blocks_fail_loudly(self):
        r=self.post([{'type':'unsupported','payload':'x'}]);self.assertEqual(r.status_code,400);self.assertFalse(self.captured)
    def test_remote_file_id_not_silently_ignored(self):
        r=self.post([{'type':'document','source':{'type':'file','file_id':'file-cloud-only'}}]);self.assertEqual(r.status_code,400);self.assertFalse(self.captured)
    def test_auth_enforced(self):
        r=self.client.post('/v1/messages',json={'model':'claude-opus-5-5','max_tokens':10,'messages':[{'role':'user','content':'hello'}]});self.assertEqual(r.status_code,401);self.assertFalse(self.captured)
    def test_forced_tool_and_none(self):
        good=json.dumps({'text':'','tool_calls':[{'name':'Read','input':{'file_path':'x'}}]})
        with self.assertRaises(BridgeProtocolError):parse_response(good,[TOOL],{'type':'none'})
        with self.assertRaises(BridgeProtocolError):parse_response('{"text":"done","tool_calls":[]}',[TOOL],{'type':'any'})
    def test_historical_tool_call_preserved(self):
        messages=[{'role':'assistant','content':[{'type':'tool_use','id':'toolu_A','name':'Read','input':{'file_path':'a.txt'}}]},{'role':'user','content':[{'type':'tool_result','tool_use_id':'toolu_A','content':'real-read-data'}]}]
        r=self.post(messages=messages);self.assertEqual(r.status_code,200)
        self.assertIn('real-read-data',self.captured[0]['query']);self.assertIn('toolu_A',self.captured[0]['query'])
    def test_large_context_full_copy_local_and_task_inline(self):
        self.answers=[json.dumps({'text':'done','tool_calls':[]})]
        r=self.post(messages=[{'role':'user','content':'HISTORY_MARKER '+('context '*15000)},{'role':'user','content':'CURRENT_TASK_749'}],tools=[TOOL],system='FULL_SYSTEM_MARKER')
        self.assertEqual(r.status_code,200)
        captured=self.captured[0]
        self.assertLessEqual(len(captured['query']),28000)
        self.assertIn('CURRENT_TASK_749',captured['query'])
        self.assertEqual(len(captured['files']),0)
        brief=json.loads(captured['query'].split('APPLICATION REQUEST JSON:\n')[1].split('\nEND APPLICATION REQUEST.')[0])
        path=pathlib.Path(brief['local_context']['exact_json_path'])
        raw=path.read_bytes()
        self.assertIn(b'FULL_SYSTEM_MARKER',raw)
        self.assertIn(b'CURRENT_TASK_749',raw)
        self.assertGreater(len(raw),100000)
        self.assertIn(b'HISTORY_MARKER',raw)
        self.assertTrue(path.exists())
    def test_bundled_context_keeps_exact_core_tool_schema(self):
        tool={'name':'Write','description':'write','input_schema':{'type':'object','properties':{'title':{'type':'string','description':'required user-facing title'}},'required':['title']}}
        self.answers=[json.dumps({'text':'done','tool_calls':[]})]
        r=self.post(messages=[{'role':'user','content':'X'*60000},{'role':'user','content':'test'}],tools=[TOOL,tool],system='Keep all system instructions')
        self.assertEqual(r.status_code,200)
        self.assertIn('"properties":{"title":{"type":"string","description":"required user-facing title"}}',self.captured[0]['query'])
    def test_oversized_system_is_not_silently_removed(self):
        r=self.post('test',tools=[TOOL],system='SYSTEM_RULE '*6000)
        self.assertEqual(r.status_code,400)
        self.assertFalse(self.captured)
        self.assertIn('no system instructions were removed',r.json()['error']['message'])
    def test_polluted_old_history_can_recover_with_bounded_inline_request(self):
        self.answers=[json.dumps({'text':'recovered','tool_calls':[]})]
        r=self.post(messages=[{'role':'user','content':'old evidence '*55000},
                              {'role':'user','content':'CURRENT_RECOVERY_TASK_612'}],tools=[TOOL])
        self.assertEqual(r.status_code,200)
        self.assertLessEqual(len(self.captured[-1]['query']),28000)
        self.assertIn('CURRENT_RECOVERY_TASK_612',self.captured[-1]['query'])
        r=self.post(messages=[{'role':'user','content':'x'*2_000_001}],tools=[TOOL])
        self.assertEqual(r.status_code,400)
    def test_upload_quota_has_specific_error(self):
        from upload_guard import UploadRateLimitError
        fake=MagicMock()
        fake.create_conversation.return_value.ask.side_effect=UploadRateLimitError()
        with patch.object(s,'Perplexity',return_value=fake):
            r=self.post()
            self.assertEqual(r.status_code,429)
            self.assertEqual(r.json()['error']['code'],'file_upload_rate_limited')
            self.assertEqual(r.headers['retry-after'],'60')
            r=self.post(stream=True)
            self.assertIn('file_upload_rate_limited',r.text)
            self.assertNotIn('"type": "tool_use"',r.text)

if __name__=='__main__':unittest.main()
