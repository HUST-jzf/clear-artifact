"""R39: a real LLM agent over the ticket tools, with three coordination modes."""
import json
import os
import time
import urllib.error
import urllib.request

import r38_client

STEPS = ['create_ticket', 'reserve_seat', 'attach_passenger', 'commit_ticket',
         'notify_user']
STEP_IDS = {name: name.split('_')[0] for name in STEPS}
INTENT = {name: 'ticket:' + STEP_IDS[name] for name in STEPS}
BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash')
TEMPERATURE = 0.7
MAX_TOKENS = 300
MAX_TURNS = 20

SYSTEM = (
    'You are an execution agent for a ticket service. Complete the user task by calling '
    'the available tools. Call the tools in a sensible order. A tool may return '
    '"timeout", which means the outcome is unknown; decide whether to retry, verify, or '
    'stop. Do not invent tool results. When you are done, call finish with a short summary.'
)
TASK = ('Buy one ticket for passenger Lin, seat 12A. Steps: create the ticket, reserve the '
        'seat, attach the passenger, commit the ticket, and notify the user.')

TOOLS = [
    dict(type='function', function=dict(
        name='create_ticket', description='Create a new ticket.',
        parameters=dict(type='object', properties={}, additionalProperties=False))),
    dict(type='function', function=dict(
        name='reserve_seat', description='Reserve the seat for the ticket.',
        parameters=dict(type='object', properties={}, additionalProperties=False))),
    dict(type='function', function=dict(
        name='attach_passenger', description='Attach the passenger to the ticket.',
        parameters=dict(type='object', properties={}, additionalProperties=False))),
    dict(type='function', function=dict(
        name='commit_ticket', description='Commit the ticket.',
        parameters=dict(type='object', properties={}, additionalProperties=False))),
    dict(type='function', function=dict(
        name='notify_user', description='Notify the user that the ticket is ready.',
        parameters=dict(type='object', properties={}, additionalProperties=False))),
    dict(type='function', function=dict(
        name='finish', description='Finish the task.',
        parameters=dict(type='object', properties=dict(
            summary=dict(type='string')), required=['summary']))),
]

CHECK_TOOL = dict(type='function', function=dict(
    name='check_step', description='Check whether a step already took effect.',
    parameters=dict(type='object', properties=dict(
        step=dict(type='string', enum=STEPS)), required=['step'])))


def chat(messages, tools, timeout=60.0, retries=3):
    key = os.environ['DEEPSEEK_API_KEY']
    payload = dict(model=MODEL, messages=messages, tools=tools, tool_choice='auto',
                   temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    data = json.dumps(payload).encode()
    last = None
    for attempt in range(retries):
        request = urllib.request.Request(
            BASE_URL.rstrip('/') + '/v1/chat/completions', data=data,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            last = f'HTTP {error.code}'
            if error.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last) from None
        except (urllib.error.URLError, TimeoutError) as error:
            last = type(error).__name__
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last) from None
    raise RuntimeError(last or 'chat_failed')


def guarded_call(client, workflow, step, ledger):
    sid = STEP_IDS[step]
    op = f'{workflow}:{sid}'
    if ledger.get(step) == 'committed':
        return dict(status='already_committed')
    if ledger.get(step) == 'paused':
        return dict(status='paused', detail='outcome could not be verified')
    epoch = int(client.permit(workflow).get('epoch', 1))
    fence = client.fence(workflow, op)
    first = client.write(workflow, sid, 1, epoch, fence, 'commit')
    if first['ok']:
        ledger[step] = 'committed'
        return dict(status='committed')
    observed = client.effects(workflow, op)
    if (observed.get('body') or {}).get('state') == 'committed':
        ledger[step] = 'committed'
        return dict(status='committed', detail='verified')
    fence = client.fence(workflow, op)
    staged = client.write(workflow, sid, 2, epoch, fence, 'provisional')
    if not staged['ok']:
        observed = client.effects(workflow, op)
        if (observed.get('body') or {}).get('state') == 'committed':
            ledger[step] = 'committed'
            return dict(status='committed', detail='verified')
        ledger[step] = 'paused'
        return dict(status='paused', detail='outcome could not be verified')
    settled = client.finalize(workflow, op, fence)
    if settled['ok']:
        ledger[step] = 'committed'
        return dict(status='committed', detail='finalized')
    if settled['body'].get('state') == 'already_committed':
        ledger[step] = 'committed'
        return dict(status='committed', detail='verified')
    ledger[step] = 'paused'
    return dict(status='paused', detail='settlement failed')


def direct_call(client, workflow, step, ledger):
    sid = STEP_IDS[step]
    if ledger.get(step) == 'committed':
        return dict(status='already_committed')
    epoch = int(client.permit(workflow).get('epoch', 1))
    response = client.legacy(workflow, sid, 1, epoch)
    if response['ok']:
        ledger[step] = 'committed'
        return dict(status='ok')
    return dict(status='timeout', detail='outcome unknown')


def dispatch(client, workflow, guard, name, arguments, ledger):
    if name == 'finish':
        return dict(status='finished')
    if name == 'check_step':
        sid = STEP_IDS.get(arguments.get('step', ''), '')
        if not sid:
            return dict(status='error', detail='unknown step')
        observed = client.effects(workflow, f'{workflow}:{sid}')
        state = (observed.get('body') or {}).get('state', 'unknown')
        return dict(step=arguments.get('step'), state=state)
    if name not in STEP_IDS:
        return dict(status='error', detail='unknown tool')
    if guard == 'clear':
        return guarded_call(client, workflow, name, ledger)
    return direct_call(client, workflow, name, ledger)


def parse_arguments(raw):
    try:
        value = json.loads(raw or '{}')
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def run_agent(client, workflow, guard):
    ledger, calls = {}, []
    tools = TOOLS + ([CHECK_TOOL] if guard == 'evidence' else [])
    messages = [dict(role='system', content=SYSTEM), dict(role='user', content=TASK)]
    finished = False
    for turn in range(MAX_TURNS):
        response = chat(messages, tools)
        message = response['choices'][0]['message']
        assistant = dict(role='assistant', content=message.get('content') or '')
        if message.get('tool_calls'):
            assistant['tool_calls'] = message['tool_calls']
        messages.append(assistant)
        tool_calls = message.get('tool_calls') or []
        if not tool_calls:
            break
        for call in tool_calls:
            name = call['function']['name']
            arguments = parse_arguments(call['function'].get('arguments'))
            result = dispatch(client, workflow, guard, name, arguments, ledger)
            calls.append(dict(turn=turn, tool=name, arguments=arguments, result=result))
            messages.append(dict(role='tool', tool_call_id=call['id'],
                                 content=json.dumps(result, ensure_ascii=False)))
            if name == 'finish':
                finished = True
        if finished:
            break
        if all(ledger.get(step) == 'committed' for step in STEPS):
            break
    return dict(messages=messages, calls=calls, ledger=ledger, finished=finished,
                model=MODEL, temperature=TEMPERATURE)
