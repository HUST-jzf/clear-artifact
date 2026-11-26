"""R35 client: CLEAR against an evidence-equivalent verify-before-retry baseline."""
import threading

import r34_client

Client = r34_client.Client
STEPS = r34_client.STEPS


def arm_revoke(client, workflow):
    return client.request('POST', f'/w/{workflow}/arm_revoke', {})


def recover(client, workflow, step, policy):
    mechanism = 'unique' if policy == 'clear' else 'none'
    return r34_client.recover(client, workflow, step, mechanism, policy,
                              threading.Barrier(1))
