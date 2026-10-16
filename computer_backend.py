"""Computer/ASI transport. Client tool execution remains in Claude, not here.

Each application turn is isolated. Reconnect only resumes the same task; an
ambiguous submission is never automatically submitted a second time.
"""
import json
import logging
import threading
import time
from uuid import uuid4

from perplexity_web_mcp.rate_limits import _create_session

BASE = 'https://www.perplexity.ai'
ASK = BASE + '/rest/sse/perplexity_ask'


class ComputerError(Exception):
    def __init__(self, message, code='computer_error', status=502):
        super().__init__(message)
        self.code, self.status = code, status


def final_answer(data):
    """Read only final visible text, never reasoning or intermediate patches."""
    texts = []
    for block in data.get('blocks') or []:
        if block.get('intended_usage') == 'workflow_root':
            for step in block.get('workflow_block', {}).get('steps', []):
                for item in step.get('items') or []:
                    text = (item.get('payload') or {}).get('text_payload', {}).get('text')
                    if isinstance(text, str) and text.strip():
                        texts.append(text)
        elif block.get('intended_usage') == 'ask_text':
            text = block.get('markdown_block', {}).get('answer')
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return '\n\n'.join(texts)


def ask_computer(query, model, token, uploader, files=(), cancel=None,
                 session_factory=None, timeout=180):
    if model not in ('pplx_asi_opus', 'pplx_asi_sonnet'):
        raise ComputerError('Unknown Computer model; fallback is disabled.', 'computer_model_invalid', 400)
    cancel = cancel or threading.Event()
    session_factory = session_factory or _create_session
    deadline = time.monotonic() + timeout
    backend_id = None
    reported_model = None
    reported_mode = None
    def check_cancel():
        if cancel.is_set():
            raise ComputerError('Client cancelled. No further Computer requests will be submitted.', 'computer_cancelled', 499)
        if time.monotonic() >= deadline:
            raise ComputerError('Computer task timed out. It was not resubmitted automatically.', 'computer_timeout', 504)
    with session_factory(token) as session:
        check_cancel()
        access = session.get(BASE + '/rest/billing/asi-access-decision',
                             params={'version':'2.18','source':'default'}, timeout=20)
        if access.status_code != 200:
            raise ComputerError('Could not verify Computer account access.', 'computer_access_check', 403 if access.status_code in (401,403) else 502)
        decision = access.json()
        if decision.get('is_out_of_credits') or decision.get('is_out_of_budget'):
            raise ComputerError('Computer credits or budget are exhausted.', 'computer_quota_exhausted', 429)
        if not decision.get('can_use_computer'):
            raise ComputerError('This account does not currently have Computer access.', 'computer_access_denied', 403)
        urls=[]
        if files:
            for info in uploader._validate_files(list(files)):
                check_cancel()
                urls.append(uploader._upload_file(info))
        params={'attachments':urls,'language':'zh-CN','timezone':'Asia/Shanghai',
                'search_focus':'internet','sources':['web'],'frontend_uuid':str(uuid4()),
                'frontend_context_uuid':str(uuid4()),'mode':'copilot','model_preference':model,
                'is_related_query':False,'is_sponsored':False,'prompt_source':'user','query_source':'home',
                'is_incognito':False,'local_search_enabled':False,'use_schematized_api':True,
                'send_back_text_in_streaming_api':False,
                'supported_block_use_cases':['answer_modes','diff_blocks','inline_assets','canvas_mode','answer_tabs'],
                'mentions':[],'dsl_query':query,'skip_search_enabled':True,'source':'default',
                'should_ask_for_mcp_tool_confirmation':True,'force_enable_browser_agent':False,'version':'2.18'}
        for attempt in range(6):
            check_cancel()
            if attempt and not backend_id:
                raise ComputerError('Computer submission ended without a task ID; it was not resubmitted.', 'computer_submission_unknown')
            url=ASK if attempt==0 else ASK+'/reconnect/'+backend_id
            body={'params':params,'query_str':query} if attempt==0 else {'reconnectInitialSnapshot':True}
            response=None
            try:
                response=session.post(url,json=body,headers={'Accept':'text/event-stream','Content-Type':'application/json',
                    'x-perplexity-request-reason':'perplexity-query-state-provider' if attempt==0 else 'reconnect-stream',
                    'x-request-id':str(uuid4())},stream=True,timeout=min(40,max(1,deadline-time.monotonic())))
                if response.status_code != 200:
                    status=response.status_code if response.status_code in (401,403,429) else 502
                    raise ComputerError(f'Computer endpoint returned HTTP {response.status_code}.', 'computer_http_error', status)
                for line in response.iter_lines():
                    check_cancel()
                    line=line.decode('utf8') if isinstance(line,bytes) else line
                    if 'end_of_stream' in line:
                        break
                    if not line.startswith('data:'):
                        continue
                    try:data=json.loads(line[5:].strip())
                    except ValueError:continue
                    if not isinstance(data,dict):continue
                    backend_id=data.get('backend_uuid') or backend_id
                    reported_model=data.get('display_model') or reported_model
                    reported_mode=data.get('mode') or reported_mode
                    if reported_model and reported_model != model:
                        raise ComputerError('Computer reported a different model. No fallback response was accepted.', 'computer_model_mismatch')
                    if data.get('error') or data.get('error_code') or data.get('status') in ('FAILED','CANCELLED','CANCELED'):
                        raise ComputerError('Computer task failed upstream.', 'computer_task_failed')
                    if data.get('status')=='COMPLETED':
                        if reported_mode!='ASI' or reported_model!=model:
                            raise ComputerError('Computer did not confirm the requested ASI route.', 'computer_route_unconfirmed')
                        answer=final_answer(data)
                        if not answer.strip():
                            raise ComputerError('Computer completed without a visible answer.', 'computer_empty_answer')
                        logging.info('Computer complete: mode=%s model=%s reconnects=%s attachments=%s',reported_mode,reported_model,attempt,len(urls))
                        return answer
            except ComputerError:
                raise
            except Exception as exc:
                # A known task may be reconnected, but never recreate a task
                # when the submission outcome is ambiguous.
                if not backend_id:
                    raise ComputerError('Computer submission was interrupted before a task ID was received; no automatic resubmission.', 'computer_submission_unknown') from None
                logging.warning('Computer stream interrupted: %s; resuming same task',type(exc).__name__)
            finally:
                if response is not None:response.close()
            check_cancel()
        raise ComputerError('Computer did not complete within the bounded reconnect attempts.', 'computer_timeout', 504)
