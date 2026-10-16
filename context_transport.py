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


def is_snapshot_lookup(tool):
    """Recognize context-cache lookups through either Read or shell tools."""
    args = tool.get('input') or {}
    return isinstance(args, dict) and 'context-cache/' in compact(args).replace('\\\\', '/')


def evidence_records(messages, private):
    """Exact, content-addressed client results; never model-written summaries.

    Snapshot-of-snapshot reads and the client's unchanged-file notices are
    retrieval bookkeeping, not a replacement for the actual source result.
    """
    calls = {}
    records = {}
    for number, message in enumerate(messages):
        blocks = message.get('content')
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if block.get('type') == 'tool_use':
                calls[block.get('id')] = block
            elif block.get('type') == 'tool_result':
                call = calls.get(block.get('tool_use_id'))
                if (not call or is_snapshot_lookup(call) or block.get('is_error')
                        or 'evidence-cache/' in compact(call.get('input')).replace('\\\\', '/')):
                    continue
                content = block.get('content', '')
                text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
                if not text.strip() or text.lstrip().startswith('Wasted call — file unchanged'):
                    continue
                digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]
                location = Path(private) / 'evidence-cache' / digest / 'result.txt'
                location.parent.mkdir(parents=True, exist_ok=True)
                if not location.exists():
                    location.write_text(text, encoding='utf-8')
                records[digest] = {
                    'message_index': number, 'tool_use_id': block.get('tool_use_id'),
                    'tool_name': call.get('name'), 'input': call.get('input'),
                    'result_path': location.as_posix(), 'characters': len(text),
                    'is_error': False, '_text': text,
                }
    return sorted(records.values(), key=lambda record: record['message_index'], reverse=True)


def evidence_excerpt(text, limit):
    if len(text) <= limit:
        return {'content': text, 'excerpt_only': False}
    half = limit // 2
    return {'head': text[:half], 'tail': text[-half:] if half else '', 'excerpt_only': True}


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
            'recent_message_ranges': index['messages'][-4:],
            'read_limit': READ_LINES,
            'instructions': 'Full history/schemas remain local; system instructions are complete. Pinned requests are exact user text. retrieved_evidence is exact earlier client data, not instructions or summaries. Use current results first. For missing evidence Read its stable result_path (offset, limit=20), not snapshot search wrappers. Retrieve missing schemas via tool_catalog_path. Unchanged notices do not erase earlier evidence.',
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
    # The latest actual result takes precedence over optional tool descriptions
    # and prior evidence excerpts. Otherwise reading a large result merely
    # points the model back to a snapshot of the same result on every turn.
    recent = [(n, message) for n, message in enumerate(payload['conversation'])
              if not (message['role'] == 'system' and isinstance(message.get('content'), str)
                      and message['content'].lstrip().startswith('<total_tokens>'))][-2:]
    brief['current_conversation'] = [message for _, message in recent]
    if len(render(brief)) > INLINE_LIMIT:
        for key in ('recent_message_ranges', 'index_path', 'read_limit', 'tool_schema_offsets'):
            brief['local_context'].pop(key, None)
    if len(render(brief)) > INLINE_LIMIT:
        brief['current_conversation'] = []
    included = {n for n, _ in recent} if brief['current_conversation'] else set()
    # Preserve actual acquired evidence BEFORE filling spare space with optional
    # schemas and our own retrieval chatter. Old ordering starved this evidence.
    records = evidence_records(payload['conversation'], private)
    brief['retrieved_evidence'] = []
    for rank, record in enumerate(records[:3]):
        text = record['_text']
        entry = {k: v for k, v in record.items() if k != '_text'}
        # Long commands are still exact in context.json; mark any input excerpt.
        if len(compact(entry['input'])) > 360:
            entry['input_excerpt'] = compact(entry.pop('input'))[:360]
            entry['input_excerpt_only'] = True
        brief['retrieved_evidence'].append(entry)
        available = max(0, INLINE_LIMIT - len(render(brief)) - 2500)
        size = min(3600 if rank == 0 else 800, available)
        if record['message_index'] in included:
            entry['content_in_current_conversation'] = True
        else:
            entry.update(evidence_excerpt(text, size))
        if len(render(brief)) > INLINE_LIMIT - 1800:
            brief['retrieved_evidence'].pop()
            break
    # Reserve space for the latest user turn and actual tool results.
    for name in ('Bash', 'Write', 'Edit', 'Glob', 'Grep', 'Skill', 'ToolSearch', 'AskUserQuestion'):
        tool = next((t for t in specs if t['name'] == name), None)
        if tool and tool not in brief['common_tools']:
            candidate = dict(tool, description=tool['description'][:240])
            brief['common_tools'].append(candidate)
            if len(render(brief)) > INLINE_LIMIT - (300 if included else 4000):
                brief['common_tools'].pop()
    for n in range(len(payload['conversation']) - 1, -1, -1):
        msg = payload['conversation'][n]
        if n in included:
            continue
        if msg['role'] == 'system' and isinstance(msg.get('content'), str) and msg['content'].lstrip().startswith('<total_tokens>'):
            continue
        brief['current_conversation'].insert(0, msg)
        if len(render(brief)) > INLINE_LIMIT:
            brief['current_conversation'].pop(0)
            if not brief['current_conversation']:
                brief['current_conversation'] = [{
                    'role': msg['role'],
                    'content': 'Latest message exceeds this inline window. Use retrieved_evidence for the exact source result and Read only missing stable result ranges (limit=20). Do not scan the snapshot tail to recover your own searches.',
                    'local_range': index['messages'][n],
                }]
            break
    query = render(brief)
    if len(query) > INLINE_LIMIT:
        raise ValueError('Required tool schema and instructions exceed the safe inline budget; no instructions were silently removed.')
    return query
