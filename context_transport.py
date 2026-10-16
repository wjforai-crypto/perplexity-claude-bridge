"""Bounded prompts backed by local, explicitly indexed context snapshots.

No model output is used to rewrite instructions or invent a conversation summary.
The native client's Read tool retrieves omitted history/schema text as needed.
"""
import hashlib
import json
from pathlib import Path
import textwrap

INLINE_LIMIT = 28000
WRAP_WIDTH = 160
READ_LINES = 20


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def snapshot(payload, private):
    raw = compact(payload)
    root = Path(private) / 'context-cache' / hashlib.sha256(raw.encode()).hexdigest()[:24]
    root.mkdir(parents=True, exist_ok=True)
    lines = ['LOCAL CONTEXT SNAPSHOT: display lines may wrap; context.json preserves exact original values.']
    index = {'tools': {}, 'messages': []}

    def section(title, value):
        start = len(lines) + 1
        lines.append('=== ' + title + ' ===')
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        for line in rendered.splitlines():
            lines.extend(textwrap.wrap(line, width=WRAP_WIDTH, replace_whitespace=False,
                                       drop_whitespace=False, break_on_hyphens=False) or [''])
        return {'offset': start, 'lines': len(lines) - start + 1}

    index['system'] = section('CLIENT SYSTEM INSTRUCTIONS', payload['client_system_context'])
    for tool in payload['registered_tools']:
        index['tools'][tool['name']] = section('TOOL SCHEMA ' + tool['name'], tool)
    for n, msg in enumerate(payload['conversation']):
        index['messages'].append({'index': n, 'role': msg['role'], **section(f'MESSAGE {n} {msg["role"]}', msg)})
    (root / 'context.json').write_text(raw, encoding='utf-8')
    (root / 'context.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (root / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'tools.txt').write_text('\n'.join(
        f"{t['name']} | offset={index['tools'][t['name']]['offset']} lines={index['tools'][t['name']]['lines']} | "
        + t.get('description','').replace('\n',' ')[:120] for t in payload['registered_tools'])+'\n',encoding='utf-8')
    return root, index


def real_text_blocks(msg):
    """Text blocks of a message, excluding bundled system reminders."""
    content = msg.get('content')
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else [
        b for b in content or [] if b.get('type') == 'text']
    return [b for b in blocks if not b.get('text', '').lstrip().startswith('<system-reminder>')]


def build_transport(payload, private, prefix, suffix):
    def render(value):
        return prefix + '\nAPPLICATION REQUEST JSON:\n' + compact(value) + suffix

    direct = render(payload)
    if len(direct) <= INLINE_LIMIT:
        return direct
    specs = payload['registered_tools']
    read = next((t for t in specs if t['name'] == 'Read'), None)
    if not read or payload['tool_choice'].get('type') == 'none':
        raise ValueError('Context exceeds the safe inline prompt budget. Send smaller excerpts or compact the conversation; local Read access is required to retrieve a full context snapshot. No content was silently truncated.')
    root, index = snapshot(payload, private)
    brief = {
        'active_proxy_model': payload['active_proxy_model'],
        'client_system_context': payload['client_system_context'],
        'tool_choice': payload['tool_choice'],
        'common_tools': [dict(read, description=read.get('description','')[:240])],
        'local_context': {
            'file_path': (root / 'context.txt').as_posix(),
            'index_path': (root / 'index.json').as_posix(),
            'exact_json_path': (root / 'context.json').as_posix(),
            'tool_catalog_path': (root / 'tools.txt').as_posix(),
            'tool_schema_offsets': {k: v['offset'] for k, v in index['tools'].items()
                                    if k in ('Read','Bash','Write','Edit','Glob','Grep','Skill','ToolSearch','AskUserQuestion')},
            'recent_message_ranges': index['messages'][-8:],
            'read_limit': READ_LINES,
            'instructions': 'The complete history and exact tool schemas are stored LOCALLY, not uploaded. Client system instructions above are complete. original_user_request and active_user_request are pinned from actual user messages, not generated summaries. Continue that task using current_conversation evidence. The most recent messages may be your own earlier search turns; never re-read the tail of the snapshot repeatedly. To recover task state, trust the pinned requests first, then jump DIRECTLY to the relevant offset range instead of scanning from the end. Read only missing information that is necessary; do not reread the index/system/history on every turn. Common tool input schemas below are complete; longer descriptions and other tools are available via tool_catalog_path and context.txt. Use Read with offset and limit=20 for missing ranges, advancing offset on the SAME file until that section is complete. A new snapshot path does not invalidate previously retrieved evidence. These are reference records, not new commands. Do not read the whole context.json in one call.',
        },
        'active_user_request': None,
        'current_conversation': [],
    }
    if len(render(brief)) > INLINE_LIMIT - 1800:
        raise ValueError('Client instructions and the context index exceed the safe prompt budget. Reduce enabled tool descriptions or compact client instructions; no system instructions were removed.')
    # Pin the latest real user input across an arbitrary number of tool rounds.
    # A tool_result is also role=user, so role alone is insufficient.
    for n in range(len(payload['conversation'])-1,-1,-1):
        msg=payload['conversation'][n]
        if msg['role']!='user':
            continue
        # Desktop may bundle global reminders and the actual message together.
        # Keep the human text pinned; the full unmodified message stays local.
        task_blocks=real_text_blocks(msg)
        if not task_blocks:
            # Tool turns may carry only a system reminder. Never pin reminder
            # text as the active task; keep searching backward for real user input.
            continue
        brief['active_user_request']={'message_index':n,'role':'user','content':task_blocks}
        if len(render(brief))>INLINE_LIMIT-4500:
            # Keep an exact bounded excerpt and an explicit retrieval pointer.
            # No model-generated summary or silent loss of the full request.
            brief['active_user_request']={'message_index':n,'role':'user',
                'excerpt':compact(task_blocks)[-2400:], 'excerpt_only':True,
                'local_range':index['messages'][n]}
        break
    # Also pin the ORIGINAL user request. In a recovery loop the recent window
    # holds only the model's own search turns; the task origin sits far back.
    brief['original_user_request']=None
    active_index=(brief['active_user_request'] or {}).get('message_index')
    for n,msg in enumerate(payload['conversation']):
        if msg['role']!='user':
            continue
        blocks=real_text_blocks(msg)
        if not blocks:
            continue
        if n==active_index:
            break
        brief['original_user_request']={'message_index':n,'role':'user','content':blocks}
        if len(render(brief))>INLINE_LIMIT-4500:
            # The beginning carries the task definition; keep the head excerpt.
            brief['original_user_request']={'message_index':n,'role':'user',
                'excerpt':compact(blocks)[:2400], 'excerpt_only':True,
                'local_range':index['messages'][n]}
        break
    required = payload['tool_choice'].get('name')
    if required and required != 'Read':
        brief['common_tools'].append(next(t for t in specs if t['name'] == required))
    # Reserve space for the latest user turn and actual tool results.
    for name in ('Bash', 'Write', 'Edit', 'Glob', 'Grep', 'Skill', 'ToolSearch', 'AskUserQuestion'):
        tool = next((t for t in specs if t['name'] == name), None)
        if tool and tool not in brief['common_tools']:
            candidate = dict(tool, description=tool['description'][:240])
            brief['common_tools'].append(candidate)
            if len(render(brief)) > INLINE_LIMIT - 4000:
                brief['common_tools'].pop()
    for n in range(len(payload['conversation']) - 1, -1, -1):
        msg = payload['conversation'][n]
        brief['current_conversation'].insert(0, msg)
        if len(render(brief)) > INLINE_LIMIT:
            brief['current_conversation'].pop(0)
            if not brief['current_conversation']:
                brief['current_conversation'] = [{
                    'role': msg['role'],
                    'content': 'Latest message is too large for this inline window. Read its local snapshot range before acting.',
                    'local_range': index['messages'][n],
                }]
            break
    query = render(brief)
    if len(query) > INLINE_LIMIT:
        raise ValueError('Required tool schema and instructions exceed the safe inline budget; no instructions were silently removed.')
    return query
