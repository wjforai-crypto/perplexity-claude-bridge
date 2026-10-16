import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from context_transport import build_transport


class ContextTransportTests(unittest.TestCase):
    def test_active_task_survives_many_tool_results_and_system_metadata(self):
        tools=[{'name':name,'description':'doc '*300,'input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}} for name in ('Read','Bash','Write')]
        tools += [{'name':f'mcp__connected_app__tool_operation_{i:03d}','description':'documentation '*70,'input_schema':{'type':'object'}} for i in range(107)]
        conversation=[{'role':'user','content':[{'type':'text','text':'ACTIVE_TASK_9814: inspect the current sheet and describe its visual content.'}]}]
        for i in range(12):
            conversation.extend([{'role':'assistant','content':[{'type':'tool_use','id':str(i),'name':'Read','input':{'file_path':'context.txt'}}]},
                                 {'role':'user','content':[{'type':'tool_result','tool_use_id':str(i),'content':'retrieved evidence '*180}]},
                                 {'role':'system','content':'<total_tokens>100000</total_tokens>'}])
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'SYSTEM_RULE '*1195,'registered_tools':tools,'tool_choice':{'type':'auto'},'conversation':conversation}
        with tempfile.TemporaryDirectory() as temp:
            q=build_transport(payload,Path(temp),'transport contract '*145,'\nEND')
            self.assertLessEqual(len(q),28000)
            self.assertIn('ACTIVE_TASK_9814',q)
            brief=json.JSONDecoder().raw_decode(q.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertIn('Bash',[t['name'] for t in brief['common_tools']])
            self.assertIn('retrieved evidence',q)
    def test_desktop_scale_tool_catalog_keeps_instructions_and_current_task(self):
        tools=[{'name':'Read','description':'Read files. '*70,'input_schema':{'type':'object','properties':{'file_path':{'type':'string'},'offset':{'type':'integer'},'limit':{'type':'integer'}}}}]
        tools += [{'name':f'mcp__connected_app__tool_operation_{i:03d}','description':'documentation '*70,'input_schema':{'type':'object'}} for i in range(109)]
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'SYSTEM_RULE '*1195,'registered_tools':tools,'tool_choice':{'type':'auto'},'conversation':[{'role':'user','content':'historical records '*25000},{'role':'user','content':'CURRENT_TASK_MARKER_9168 '+('current instructions '*60)}]}
        with tempfile.TemporaryDirectory() as temp:
            q=build_transport(payload,Path(temp),'transport contract '*145,'\nEND')
            self.assertLessEqual(len(q),28000)
            self.assertIn(payload['client_system_context'],q)
            self.assertIn('CURRENT_TASK_MARKER_9168',q)
            brief=json.JSONDecoder().raw_decode(q.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertIn(tools[-1]['name'],Path(brief['local_context']['tool_catalog_path']).read_text(encoding='utf8'))
            stored=list(Path(temp).glob('context-cache/*/context.json'))
            self.assertEqual(json.loads(stored[0].read_text(encoding='utf8')),payload)
    def test_reminder_only_tool_turns_do_not_replace_active_task(self):
        tool={'name':'Read','description':'Read a local file.','input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}}
        conversation=[{'role':'user','content':'ACTUAL_USER_TASK_347: inspect the image and report visible content.'}]
        for i in range(15):
            conversation.extend([
                {'role':'assistant','content':[{'type':'tool_use','id':str(i),'name':'Read','input':{'file_path':'fixture.txt'}}]},
                {'role':'user','content':[{'type':'tool_result','tool_use_id':str(i),'content':'evidence '*1000},
                                          {'type':'text','text':'<system-reminder>Tool output reminder only.</system-reminder>'}]}
            ])
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'Rules','registered_tools':[tool],
                 'tool_choice':{'type':'auto'},'conversation':conversation}
        with tempfile.TemporaryDirectory() as temp:
            q=build_transport(payload,Path(temp),'Transport contract','')
            self.assertIn('ACTUAL_USER_TASK_347',q)
            brief=json.JSONDecoder().raw_decode(q.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertEqual(brief['active_user_request']['message_index'],0)
            self.assertNotIn('Tool output reminder only',json.dumps(brief['active_user_request'],ensure_ascii=False))

if __name__=='__main__':unittest.main()
