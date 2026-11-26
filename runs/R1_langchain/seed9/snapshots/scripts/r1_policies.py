"""R1 single-mechanism policies over the capability-space source."""
from clear_assurance import decide, digest, positive


def event(host, action, body):
    return dict(seq=0, context=host.context.copy(), manifest=digest(host.current_manifest),
                action=action, body=body)


async def run(host, policy, budget=4, after_action=None):
    events, steps = [], []
    qualified = host.initial_qualification

    async def record(action, body):
        item = dict(seq=len(events), context=host.context.copy(),
                    manifest=digest(host.current_manifest), action=action, body=body)
        events.append(item)
        if after_action:
            await after_action(len(events))

    if policy == 'pause':
        return dict(policy=policy, context=host.context, origin=host.origin,
                    initial_observations=host.initial_observations, terminal='pause',
                    reason='single_pause', events=events, steps=steps)

    if policy == 'clear':
        while True:
            await host.refresh()
            decision = decide(host.origin, host.current_manifest, host.capabilities, qualified,
                              events, budget)
            steps.append(dict(observation_count=len(events), manifest=host.current_manifest,
                              qualification=qualified, decision=decision))
            action = decision['action']
            if action in ['pause', 'complete']:
                return dict(policy=policy, context=host.context, origin=host.origin,
                            initial_observations=host.initial_observations, terminal=action,
                            reason=decision['reason'], events=events, steps=steps)
            body = await host.action(action, qualification=qualified)
            await record(action, body)
            if action == 'qualify':
                qualified = body

    if policy == 'idem_retry':
        body = await host.retry()
        await record('retry', body)
        terminal = 'complete' if positive(body, host.origin) else 'pause'
        return dict(policy=policy, context=host.context, origin=host.origin,
                    initial_observations=host.initial_observations, terminal=terminal,
                    reason='idempotent_retry' if terminal == 'complete' else 'retry_unconfirmed',
                    events=events, steps=steps)

    if policy == 'query_retry':
        body = await host.action('query')
        await record('query', body)
        if positive(body, host.origin):
            return dict(policy=policy, context=host.context, origin=host.origin,
                        initial_observations=host.initial_observations, terminal='complete',
                        reason='query_receipt', events=events, steps=steps)
        if body.get('complete') is not True or body.get('state') != 'not_committed':
            return dict(policy=policy, context=host.context, origin=host.origin,
                        initial_observations=host.initial_observations, terminal='pause',
                        reason='query_unknown', events=events, steps=steps)
        retried = await host.retry()
        await record('retry', retried)
        terminal = 'complete' if positive(retried, host.origin) else 'pause'
        return dict(policy=policy, context=host.context, origin=host.origin,
                    initial_observations=host.initial_observations, terminal=terminal,
                    reason='query_then_retry' if terminal == 'complete' else 'retry_unconfirmed',
                    events=events, steps=steps)

    if policy == 'reauth_retry':
        described = await host.call('describe', {})
        host.current_manifest = described['manifest']
        host.current_route = described['route']
        host.capabilities = described['capabilities']
        if described['route'].get('allowed') is not True:
            await host.call('reauthorize', dict(operation_id=host.context['operation_id'],
                                                intent=host.context['intent']))
            await host.refresh()
        body = await host.retry()
        await record('retry', body)
        terminal = 'complete' if positive(body, host.origin) else 'pause'
        return dict(policy=policy, context=host.context, origin=host.origin,
                    initial_observations=host.initial_observations, terminal=terminal,
                    reason='reauth_retry' if terminal == 'complete' else 'retry_unconfirmed',
                    events=events, steps=steps)

    raise ValueError(policy)
