"""Durable fake-provider state for the operator's resumable prepared execution.

Only the synthetic wallet and provider objects are stored. Authentication state,
request headers and credentials are never persisted. Ordinary fake API clients
and the standalone demo keep their existing in-memory transport.
"""
import json as jsonlib
from decimal import Decimal

from ..connectors.airwallex.client import AirwallexClient
from ..connectors.airwallex.fake import FakeTransport
from ..jobs.store import JobStore


class PreparedTransport(FakeTransport):
    def __init__(self, jobs: JobStore, run_id: str):
        super().__init__()
        self.jobs, self.run_id = jobs, run_id
        state = jobs.get("demo_provider", run_id)
        if state is not None:
            state = jsonlib.loads(state, object_hook=lambda value: (
                Decimal(value["$decimal"]) if set(value) == {"$decimal"} else value))
            self.balances = state["balances"]
            self.objects = state["objects"]
            self.quotes = state["quotes"]
            self._serial = state["serial"]
            self.clock.now = state["clock"]

    def send(self, method, path, json=None, headers=None):
        response = super().send(method, path, json=json, headers=headers)
        # Commit the fake's effect before exposing its response to the execution gateway.
        self.jobs.put("demo_provider", self.run_id, jsonlib.dumps({
            "balances": self.balances, "objects": self.objects, "quotes": self.quotes,
            "serial": self._serial, "clock": self.clock.now},
            default=lambda value: {"$decimal": str(value)}))
        return response


def client_for(jobs: JobStore, run_id: str) -> AirwallexClient:
    transport = PreparedTransport(jobs, run_id)
    return AirwallexClient(transport, clock=transport.clock)
