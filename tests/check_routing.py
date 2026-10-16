"""Offline checks: model routing and authentication. No upstream requests."""
import json,pathlib,sys,os,tempfile,atexit
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
_private = tempfile.TemporaryDirectory(prefix='bridge-routing-')
atexit.register(_private.cleanup)
os.environ['PWM_PRIVATE_DIR'] = _private.name
(pathlib.Path(_private.name)/'api-key.txt').write_text('offline-fixture-key', encoding='utf-8')
import pwm_local
from fastapi.testclient import TestClient
s=pwm_local.configure_api()
assert s.ConversationConfig().source_focus==[]
assert s.ConversationConfig().search_focus.value=='writing'
from perplexity_web_mcp.core import Conversation
long_query='长上下文回归测试。'*5000+' END_MARKER'
fake_http=MagicMock()
conversation=Conversation(fake_http,s.ConversationConfig(model=s.get_model('claude-sonnet-5-5')))
with patch.object(Conversation,'_stream',return_value=iter(())) as stream_mock:
    conversation.ask(long_query,stream=True,init_query=long_query)
    fake_http.init_search.assert_called_once_with('Claude Desktop conversation')
    assert stream_mock.call_args.args[0]['query_str']==long_query
settings=s.ServerConfig(session_token='offline-test-only',api_key='offline-local-secret')
with patch.object(s.ServerConfig,'from_env',return_value=settings),patch.object(s,'Perplexity'):
    with TestClient(s.app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/v1/models').status_code in (401,403)
        hdr={'Authorization':'Bearer offline-local-secret','anthropic-version':'2023-06-01'}
        response=client.get('/v1/models',headers=hdr)
        assert response.status_code==200, response.text
        assert {x['id'] for x in response.json()['data']}=={'claude-opus-5-5','claude-sonnet-5-5'}
        for wrong in ['opus','claude-haiku-4-5','unknown']:
            r=client.post('/v1/messages',headers=hdr,json={'model':wrong,'max_tokens':20,'messages':[{'role':'user','content':'test'}]})
            assert r.status_code==400,(wrong,r.text)
        r=client.post('/v1/messages',json={'model':'claude-opus-5-5','max_tokens':20,'messages':[{'role':'user','content':'test'}]})
        assert r.status_code in (401,403),r.text
        assert s.get_model('claude-opus-5-5').identifier=='claude55opus'
        assert s.get_model('claude-opus-5-5',True).identifier=='claude55opusthinking'
        assert s.get_model('claude-sonnet-5-5').identifier=='claude55sonnet'
        assert s.get_model('claude-sonnet-5-5',True).identifier=='claude55sonnetthinking'
print(json.dumps({'offline_checks':'passed','upstream_calls':0,'checks':['health','authentication','two_model_catalog','reject_unknown_and_mock_models','exact_opus55_and_sonnet55_mapping']}))
