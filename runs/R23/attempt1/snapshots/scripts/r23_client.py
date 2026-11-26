"""R23 client: the R19 controller with an option to regenerate the idempotency key.

`idem_retry` in R15/R18/R21 always retries with the same key, which is the most
favourable assumption for a key-based baseline: the client remembers the logical
operation across attempts. Many hosts rebuild the tool call on retry (a new
request id per attempt) and therefore send a different key. This class models
that without touching the controller: when `fresh_keys` is set, every attempt
travels under its own key.
"""
import r19_client as base


class Client(base.Client):
    def __init__(self, base_url, fresh_keys=False):
        super().__init__(base_url)
        self.fresh_keys = fresh_keys

    def post_step(self, workflow, step, attempt, epoch, key):
        if self.fresh_keys and key is not None:
            key = f'{key}#a{attempt}'
        return super().post_step(workflow, step, attempt, epoch, key)
