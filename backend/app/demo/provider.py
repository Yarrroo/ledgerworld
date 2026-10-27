"""Durable fake-provider state for the operator's resumable prepared execution.

Only the synthetic wallet and provider objects are stored. Authentication state,
request headers and credentials are never persisted. Ordinary fake API clients
and the standalone demo keep their existing in-memory transport.
"""
import json as jsonlib
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from ..connectors.airwallex.client import AirwallexClient, ProviderObject
from ..connectors.airwallex.fake import FakeTransport
from ..connectors.airwallex.transport import Response, decode_body, encode_body
from ..execution import outbox
from ..execution.gateway import ConnectorProvider, Gateway, deposit_reference
from ..jobs.store import JobStore, records


class PreparedTransport(FakeTransport):
    def __init__(self, jobs: JobStore, run_id: str):
        super().__init__()
        self.jobs, self.run_id = jobs, run_id
        self.where = (records.c.kind == "demo_provider", records.c.key == run_id)
        # Insert-only: a second constructor must never reset an existing synthetic wallet.
        with jobs.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(insert(records).values(
                        kind="demo_provider", key=run_id, body=self._dump(),
                        updated_at=datetime.now(UTC).isoformat()))
            except IntegrityError:
                pass

    def _dump(self):
        return jsonlib.dumps({
            "balances": self.balances, "objects": self.objects, "quotes": self.quotes,
            "serial": self._serial, "clock": self.clock.now},
            default=lambda value: {"$decimal": str(value)}, sort_keys=True)

    def _restore(self, text):
        state = jsonlib.loads(text)
        if isinstance(state, str):  # the original command stored a JSON string as its body
            state = jsonlib.loads(state)
        state = jsonlib.loads(jsonlib.dumps(state), object_hook=lambda value: (
            Decimal(value["$decimal"]) if set(value) == {"$decimal"} else value))
        self.balances, self.objects, self.quotes = (
            state["balances"], state["objects"], state["quotes"])
        self._serial, self.clock.now = state["serial"], state["clock"]

    def send(self, method, path, json=None, headers=None):
        error = None
        with self.jobs.engine.begin() as conn:
            # A write locks this row on both SQLite and PostgreSQL. Reload, perform the fake
            # request and commit its state under that lock: a stale client cannot overwrite it.
            conn.execute(update(records).where(*self.where).values(
                updated_at=records.c.updated_at))
            before = conn.execute(select(records.c.body).where(*self.where)).scalar_one()
            self._restore(before)
            try:
                existing = next((obj for obj in self.objects["deposits"].values()
                                 if obj.get("reference") == (json or {}).get("reference")), None)
                if (method == "POST" and path == "/api/v1/simulation/deposit/create"
                        and (json or {}).get("reference") and existing is not None):
                    # Local fake only: the reference identifies one durable preparation leg.
                    # This is not a claim about the sandbox's deposit-idempotency contract.
                    text = encode_body(self._public(existing)).decode()
                    response = Response(201, decode_body(text),
                                        {"content-type": "application/json"}, text)
                else:
                    response = super().send(method, path, json=json, headers=headers)
            except Exception as caught:  # noqa: BLE001 — persist accepted fake effects before rethrow
                error = caught
            after = self._dump()
            if after != before:
                conn.execute(update(records).where(*self.where).values(body=after))
        if error is not None:
            raise error
        return response

    def deposits(self):
        with self.jobs.engine.begin() as conn:
            self._restore(conn.execute(select(records.c.body).where(*self.where)).scalar_one())
        return [self._public(obj) for obj in self.objects["deposits"].values()]


class PreparedProvider(ConnectorProvider):
    """Only the durable local fake can authoritatively look up Mode B deposits.

    The real sandbox connector deliberately retains its no-lookup/no-blind-retry rule.
    """
    def find(self, leg):
        if leg.kind != "advance" or self.leg_mode != "B":
            return super().find(leg)
        return [self._ours(leg, ProviderObject.parse("deposit", raw))
                for raw in self.client.transport.deposits()
                if raw.get("reference") == deposit_reference(leg)]

    def get(self, leg):
        if leg.kind != "advance" or self.leg_mode != "B":
            return super().get(leg)
        for obj in self.find(leg):
            if obj.provider_id == leg.provider_id:
                return obj
        raise outbox.LookupFailed("the local fake has no matching deposit")


class PreparedGateway(Gateway):
    def __init__(self, store, client, **kwargs):
        super().__init__(store, client, **kwargs)
        self.provider = PreparedProvider(client, self.leg_mode,
                                         target=lambda leg: self.bound(leg).to_currency)


def client_for(jobs: JobStore, run_id: str) -> AirwallexClient:
    transport = PreparedTransport(jobs, run_id)
    return AirwallexClient(transport, clock=transport.clock)
