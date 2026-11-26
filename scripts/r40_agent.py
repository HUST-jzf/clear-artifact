"""R40: a real LLM agent with intent-bearing tool arguments and two recovery scenarios."""
import json
import os
import time
import urllib.error
import urllib.request

STEPS = ['create_ticket', 'reserve_seat', 'attach_passenger', 'commit_ticket',
         'notify_user']
STEP_IDS = {name: name.split('_')[0] for name in STEPS}
SEAT_STEPS = ('reserve_seat', 'attach_passenger')
DEFAULT_SEAT = '12A'
BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash')
TEMPERATURE = 0.7
MAX_TOKENS = 300
MAX_TURNS = 20
MAX_NUDGES = 2
NUDGE = 'Continue the task. Call finish when you are done.'

SYSTEM = (
    'You are an execution agent for a ticket service. Complete the user task by calling '
    'the available tools. Call the tools in a sensible order. A tool may return '
    '"timeout", which means the outcome is unknown; decide whether to retry, verify, or '
    'stop. Do not invent tool results. When you are done, call finish with a short summary.'
)
TASK = ('Buy one ticket for passenger Lin, seat 12A. Steps: create the ticket, reserve the '
        'seat, attach the passenger, commit the ticket, and notify the user.')
CHANGE = ('Update: the passenger changed their seat to 14C. Make sure the passenger is '
          'attached with seat 14C before committing.')
RESUME = ('The service has been repaired. Resume the ticket task for passenger Lin, seat '
          '12A, using any evidence you can obtain.')

TOOLS = [
    dict(type='function', function=dict(
        name='create_ticket', description='Create a new ticket.',
        parameters=dict(type='object', properties=dict(
            passenger=dict(type='string')), required=[]))),
    dict(type='function', function=dict(
        name='reserve_seat', description='Reserve a seat for the ticket, e.g. seat 12A.',
        parameters=dict(type='object', properties=dict(
            seat=dict(type='string')), required=['seat']))),
    dict(type='function', function=dict(
        name='attach_passenger',
        description='Attach the passenger to the ticket for a specific seat, e.g. 12A.',
        parameters=dict(type='object', properties=dict(
            seat=dict(type='string')), required=['seat']))),
    dict(type='function', function=dict(
        name='commit_ticket', description='Commit the ticket.',
        parameters=dict(type='object', properties=dict(), additionalProperties=False))),
    dict(type='function', function=dict(
        name='notify_user', description='Notify the user that the ticket is ready.',
        parameters=dict(type='object', properties=dict(), additionalProperties=False))),
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


def seat_of(step, arguments):
    if step not in SEAT_STEPS:
        return None
    seat = str(arguments.get('seat') or '').strip()
    return seat or DEFAULT_SEAT


def intent_of(step, seat):
    sid = STEP_IDS[step]
    return f'ticket:{sid}:{seat}' if seat else f'ticket:{sid}'


def op_of(guard, workflow, step, seat):
    """CLEAR scopes the binding by intent; the two baselines keep one record per step."""
    sid = STEP_IDS[step]
    if guard == 'clear' and seat:
        return f'{workflow}:{sid}:{seat}'
    return f'{workflow}:{sid}'


def key_of(step, seat):
    return f'{step}:{seat or "-"}'


def guarded_call(client, workflow, step, seat, ledger):
    op = op_of('clear', workflow, step, seat)
    intent = intent_of(step, seat)
    key = key_of(step, seat)
    if ledger.get(key) == 'committed':
        return dict(status='already_committed')
    if ledger.get(key) == 'paused':
        return dict(status='paused', detail='outcome could not be verified')
    epoch = int(client.permit(workflow).get('epoch', 1))
    observed = client.effects(workflow, op)
    if (observed.get('body') or {}).get('state') == 'committed':
        ledger[key] = 'committed'
        return dict(status='committed', detail='observed_before_write')
    fence = client.fence(workflow, op)
    if fence is None:
        observed = client.effects(workflow, op)
        if (observed.get('body') or {}).get('state') == 'committed':
            ledger[key] = 'committed'
            return dict(status='committed', detail='verified')
        ledger[key] = 'paused'
        return dict(status='paused', detail='fence_unavailable')
    first = client.write(workflow, op, STEP_IDS[step], 1, epoch, intent, fence, 'commit')
    if first['ok']:
        ledger[key] = 'committed'
        return dict(status='committed')
    observed = client.effects(workflow, op)
    if (observed.get('body') or {}).get('state') == 'committed':
        ledger[key] = 'committed'
        return dict(status='committed', detail='verified')
    fence = client.fence(workflow, op)
    if fence is None:
        ledger[key] = 'paused'
        return dict(status='paused', detail='fence_unavailable')
    staged = client.write(workflow, op, STEP_IDS[step], 2, epoch, intent, fence,
                          'provisional')
    if not staged['ok']:
        observed = client.effects(workflow, op)
        if (observed.get('body') or {}).get('state') == 'committed':
            ledger[key] = 'committed'
            return dict(status='committed', detail='verified')
        ledger[key] = 'paused'
        return dict(status='paused', detail='outcome could not be verified')
    settled = client.finalize(workflow, op, fence)
    if settled['ok']:
        ledger[key] = 'committed'
        return dict(status='committed', detail='finalized')
    if settled['body'].get('state') == 'already_committed':
        ledger[key] = 'committed'
        return dict(status='committed', detail='verified')
    ledger[key] = 'paused'
    return dict(status='paused', detail='settlement failed')


def direct_call(client, workflow, step, seat, ledger):
    op = op_of('blind', workflow, step, seat)
    intent = dict(op=op, value=intent_of(step, seat))
    key = key_of(step, seat)
    if ledger.get(key) == 'committed':
        return dict(status='already_committed')
    epoch = int(client.permit(workflow).get('epoch', 1))
    response = client.legacy(workflow, STEP_IDS[step], 1, epoch, intent)
    if response['ok']:
        ledger[key] = 'committed'
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
    seat = seat_of(name, arguments)
    if guard == 'clear':
        return guarded_call(client, workflow, name, seat, ledger)
    return direct_call(client, workflow, name, seat, ledger)


def parse_arguments(raw):
    try:
        value = json.loads(raw or '{}')
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def run_agent(client, workflow, guard, scenario='intent_change', opening=None):
    ledger, calls, seats = {}, [], []
    tools = TOOLS + ([CHECK_TOOL] if guard == 'evidence' else [])
    messages = [dict(role='system', content=SYSTEM), dict(role='user', content=TASK)]
    if opening:
        messages.append(dict(role='user', content=opening))
    finished = injected = False
    last_seat = DEFAULT_SEAT
    last_attach_seat = None
    attach_seats = []
    nudges = 0
    for turn in range(MAX_TURNS):
        response = chat(messages, tools)
        message = response['choices'][0]['message']
        assistant = dict(role='assistant', content=message.get('content') or '')
        if message.get('tool_calls'):
            assistant['tool_calls'] = message['tool_calls']
        messages.append(assistant)
        tool_calls = message.get('tool_calls') or []
        if not tool_calls:
            if nudges < MAX_NUDGES and not finished:
                messages.append(dict(role='user', content=NUDGE))
                nudges += 1
                continue
            break
        for call in tool_calls:
            name = call['function']['name']
            arguments = parse_arguments(call['function'].get('arguments'))
            result = dispatch(client, workflow, guard, name, arguments, ledger)
            calls.append(dict(turn=turn, tool=name, arguments=arguments, result=result))
            messages.append(dict(role='tool', tool_call_id=call['id'],
                                 content=json.dumps(result, ensure_ascii=False)))
            if name in SEAT_STEPS:
                seats.append(seat_of(name, arguments))
                last_seat = seats[-1]
                if name == 'attach_passenger':
                    last_attach_seat = seats[-1]
                    attach_seats.append(seats[-1])
            if name == 'finish':
                finished = True
            if (scenario == 'intent_change' and not injected
                    and name == 'attach_passenger'):
                messages.append(dict(role='user', content=CHANGE))
                injected = True
        if finished:
            break
        if all(any(key.startswith(step + ':') and value == 'committed'
                   for key, value in ledger.items()) for step in STEPS):
            break
    return dict(messages=messages, calls=calls, ledger=ledger, finished=finished,
                injected=injected, nudges=nudges, last_seat=last_seat,
                last_attach_seat=last_attach_seat, attach_seats=attach_seats, seats=seats,
                model=MODEL, temperature=TEMPERATURE)
