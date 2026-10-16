import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from context_transport import build_transport, evidence_records, is_snapshot_lookup


class ContextTransportTests(unittest.TestCase):
    def test_latest_full_source_result_precedes_optional_schemas(self):
        read={'name':'Read','description':'Read local text.','input_schema':{'type':'object','properties':{'file_path':{'type':'string'}}}}
        tools=[read]+[{'name':name,'description':'tool description '*60,
            'input_schema':{'type':'object','properties':{'command':{'type':'string','description':'schema detail '*160}}}}
            for name in ('Bash','Write','Edit','Glob','Grep')]
        report='REPORT_HEAD '+('exact source '*650)+' REPORT_TAIL'
        messages=[{'role':'user','content':'Continue the implementation from the report.'},
            {'role':'assistant','content':[{'type':'tool_use','id':'report','name':'Read','input':{'file_path':'handoff.md'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'report','content':report}]},
            {'role':'system','content':'<total_tokens>14990533 tokens left</total_tokens>'}]
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'S'*13146,
            'registered_tools':tools,'tool_choice':{'type':'auto'},'conversation':messages}
        with tempfile.TemporaryDirectory() as temp:
            query=build_transport(payload,Path(temp),'protocol '*280,'\nEND')
            brief=json.JSONDecoder().raw_decode(query.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertLessEqual(len(query),28000)
            self.assertEqual(brief['client_system_context'],payload['client_system_context'])
            self.assertEqual(brief['current_conversation'][-1]['content'][0]['content'],report)
            self.assertNotIn('Latest message exceeds',query)

    def test_evidence_cache_keeps_exact_results_and_skips_recovery_wrappers(self):
        messages=[
            {'role':'assistant','content':[{'type':'tool_use','id':'report','name':'Read','input':{'file_path':'project/report.md'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'report','content':'EXACT report\nline 2'}]},
            {'role':'assistant','content':[{'type':'tool_use','id':'snapshot','name':'Read','input':{'file_path':'private/context-cache/hash/context.txt'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'snapshot','content':'wrapper about earlier tool_result'}]},
            {'role':'assistant','content':[{'type':'tool_use','id':'again','name':'Read','input':{'file_path':'project/report.md'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'again','content':'Wasted call — file unchanged since your last Read.'}]}]
        with tempfile.TemporaryDirectory() as temp:
            first=evidence_records(messages,Path(temp))
            self.assertEqual(len(first),1)
            location=Path(first[0]['result_path'])
            self.assertEqual(location.read_text(encoding='utf-8'),'EXACT report\nline 2')
            before=location.stat().st_mtime_ns
            second=evidence_records(messages,Path(temp))
            self.assertEqual(second[0]['result_path'],first[0]['result_path'])
            self.assertEqual(location.stat().st_mtime_ns,before)

    def test_windows_shell_snapshot_lookups_are_bookkeeping(self):
        self.assertTrue(is_snapshot_lookup({'name':'Bash','input':{
            'command':'cat "E:\\proxy\\private\\context-cache\\hash\\context.txt"'}}))
        self.assertFalse(is_snapshot_lookup({'name':'Read','input':{'file_path':'project/report.md'}}))

    def test_handoff_evidence_survives_snapshot_search_churn(self):
        tools=[{'name':name,'description':'tool documentation '*80,
                'input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}}
               for name in ('Read','Bash','Write','Edit','Glob','Grep','Skill','ToolSearch','AskUserQuestion')]
        tools += [{'name':f'mcp__app__operation_{i}','description':'documentation '*70,
                   'input_schema':{'type':'object'}} for i in range(101)]
        report='HANDOFF_PROGRESS_MARKER: implementation is pending; next step is to inspect app.js.\n'+('source evidence '*450)
        messages=[{'role':'user','content':'Confirm progress from the handoff and continue the implementation.'},
                  {'role':'assistant','content':[{'type':'tool_use','id':'handoff','name':'Read','input':{'file_path':'project/handoff.md'}}]},
                  {'role':'user','content':[{'type':'tool_result','tool_use_id':'handoff','content':report}]}]
        for i in range(12):
            messages += [
                {'role':'assistant','content':[{'type':'tool_use','id':str(i),'name':'Read',
                    'input':{'file_path':f'private/context-cache/hash{i}/context.txt','offset':4000+20*i,'limit':20}}]},
                {'role':'user','content':[{'type':'tool_result','tool_use_id':str(i),
                    'content':f'{4000+20*i} === MESSAGE {i} user === tool_result wrapper only'}]},
                {'role':'system','content':'<total_tokens>14990533 tokens left</total_tokens>'}]
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'S'*13146,
                 'registered_tools':tools,'tool_choice':{'type':'auto'},'conversation':messages}
        with tempfile.TemporaryDirectory() as temp:
            query=build_transport(payload,Path(temp),'transport protocol '*170,'\nEND')
            self.assertLessEqual(len(query),28000)
            self.assertIn('HANDOFF_PROGRESS_MARKER',query)

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
    def test_original_request_pinned_alongside_active_task(self):
        tool={'name':'Read','description':'Read a local file.','input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}}
        conversation=[{'role':'user','content':'ORIGINAL_TASK_552: rebuild the landing page hero section.'}]
        for i in range(12):
            conversation.extend([
                {'role':'assistant','content':[{'type':'tool_use','id':str(i),'name':'Read','input':{'file_path':'fixture.txt'}}]},
                {'role':'user','content':[{'type':'tool_result','tool_use_id':str(i),'content':'evidence '*900}]}
            ])
        conversation.append({'role':'user','content':'ACTIVE_CONTINUE_553: carry on.'})
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'Rules','registered_tools':[tool],
                 'tool_choice':{'type':'auto'},'conversation':conversation}
        with tempfile.TemporaryDirectory() as temp:
            q=build_transport(payload,Path(temp),'Transport contract','')
            self.assertLessEqual(len(q),28000)
            self.assertIn('ORIGINAL_TASK_552',q)
            self.assertIn('ACTIVE_CONTINUE_553',q)
            brief=json.JSONDecoder().raw_decode(q.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertEqual(brief['original_user_request']['message_index'],0)
            self.assertEqual(brief['active_user_request']['message_index'],len(conversation)-1)
    def test_original_request_not_duplicated_when_same_as_active(self):
        tool={'name':'Read','description':'Read a local file.','input_schema':{'type':'object','properties':{'file_path':{'type':'string'}},'required':['file_path']}}
        conversation=[{'role':'user','content':'ONLY_TASK_554: describe this sheet. '+('detail '*4000)}]
        payload={'active_proxy_model':'claude-opus-5-5','client_system_context':'Rules','registered_tools':[tool],
                 'tool_choice':{'type':'auto'},'conversation':conversation}
        with tempfile.TemporaryDirectory() as temp:
            q=build_transport(payload,Path(temp),'Transport contract','')
            brief=json.JSONDecoder().raw_decode(q.split('APPLICATION REQUEST JSON:\n')[1])[0]
            self.assertIsNone(brief.get('original_user_request'))
            self.assertEqual(brief['active_user_request']['message_index'],0)

if __name__=='__main__':unittest.main()
