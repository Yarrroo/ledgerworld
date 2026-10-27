"""Actor memory for one branch, held in graph memory under the branch's own namespace.

A branch's memory lives under ``world/<world_id>/branch/<branch_id>`` (``namespace_for``) and in
one graph whose id is derived from that namespace, so the live client keeps branches apart by id
prefix and ``FakeGraphMemory`` additionally refuses a reach into another namespace's graph. Each
record is one episode; a ``BranchMemory`` keeps the uuids it wrote, in order, and reads them back
through the client, so a read always goes through the client's ownership check.

``BranchMemory`` refuses a read of any namespace but its own with ``NamespaceViolation`` itself,
which holds for the live client too. ``snapshot()`` pins the records as they are now, frozen; a
later write to the parent cannot change a snapshot, and ``MemorySnapshot.restore_into`` copies
the pinned records into a child branch's fresh namespace, which is how a fork starts.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from typing import Any

from ..decisions.nonanticipativity import canonical
from ..testing.fake_graph_memory import NAMESPACE_RE, NamespaceViolation, namespace_for

__all__ = [
    "BranchMemory",
    "MemoryRecord",
    "MemorySnapshot",
    "NamespaceViolation",
    "graph_id_for",
    "namespace_for",
]

RECORD_SOURCE = "ledgerworld-memory"


def graph_id_for(namespace: str, instance: str | None = None) -> str:
    """The graph that holds a namespace's records; distinct namespaces get distinct ids.

    ``instance`` names another store for the same namespace (a replay of its branch), so the
    namespace's own graph is never the one created, written or deleted for it.
    """

    key = namespace if instance is None else f"{namespace}#{instance}"
    return "lw-mem-" + hashlib.sha256(key.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class MemoryRecord:
    """One remembered fact of one actor; ``seq`` is its position in its namespace."""

    namespace: str
    actor_id: str
    key: str
    value: str
    round: int
    seq: int


@dataclass(frozen=True)
class MemorySnapshot:
    """A branch's records pinned at one moment; nothing written later reaches it."""

    world_id: str
    branch_id: str
    namespace: str
    records: tuple[MemoryRecord, ...]

    def digest(self) -> str:
        """sha256 of the records as canonical JSON, for comparing captures."""

        return hashlib.sha256(canonical([asdict(r) for r in self.records]).encode()).hexdigest()

    def restore_into(self, child: BranchMemory) -> tuple[MemoryRecord, ...]:
        """Copy the pinned records, in order, into an empty sibling namespace of this world."""

        if child.world_id != self.world_id:
            raise ValueError(f"cannot restore {self.namespace} into world {child.world_id}")
        if child.namespace == self.namespace:
            raise ValueError(f"cannot restore {self.namespace} into itself")
        if child._uuids:
            raise ValueError(f"{child.namespace} already holds records; restore needs it empty")
        return tuple(
            child.write_record(r.actor_id, r.key, r.value, r.round) for r in self.records
        )


class BranchMemory:
    """One branch's memory, bound to ``namespace_for(world_id, branch_id)``.

    ``client`` is a graph-memory client shaped like ``zep_cloud.Zep`` (``FakeGraphMemory`` in
    tests). A client that carries a ``namespace`` must carry this branch's. Creating a
    ``BranchMemory`` creates its graph; a second one for the same namespace on the same store
    is refused by the client, unless it names its own ``instance``: the same logical namespace
    in a graph of its own (``graph_id_for``), which is how a replay runs beside its original.
    """

    def __init__(
        self, client: Any, world_id: str, branch_id: str, *, instance: str | None = None
    ) -> None:
        namespace = namespace_for(world_id, branch_id)
        if not NAMESPACE_RE.match(namespace):
            raise ValueError(f"world and branch ids may not hold '/' or spaces: {namespace!r}")
        bound = getattr(client, "namespace", namespace)
        if bound != namespace:
            raise NamespaceViolation(f"a client bound to {bound} cannot serve {namespace}")
        self.client = client
        self.world_id = world_id
        self.branch_id = branch_id
        self.namespace = namespace
        self.graph_id = graph_id_for(namespace, instance)
        self._uuids: list[str] = []
        self._lock = threading.Lock()
        client.graph.create(graph_id=self.graph_id, name=namespace)

    def write_record(self, actor_id: str, key: str, value: str, round_: int) -> MemoryRecord:
        """Append one record to this branch's namespace and return it."""

        if not isinstance(value, str):
            raise TypeError(f"a memory value is text, got {type(value).__name__}")
        if not isinstance(round_, int) or isinstance(round_, bool) or round_ < 0:
            raise ValueError(f"round must be a non-negative integer, got {round_!r}")
        body = {"actor_id": actor_id, "key": key, "value": value, "round": round_}
        with self._lock:
            episode = self.client.graph.add(
                graph_id=self.graph_id,
                type="json",
                data=canonical(body),
                source_description=RECORD_SOURCE,
            )
            self._uuids.append(episode.uuid_)
            return MemoryRecord(self.namespace, actor_id, key, value, round_, len(self._uuids) - 1)

    def retrieve(
        self, *, namespace: str | None = None, actor_id: str | None = None
    ) -> tuple[MemoryRecord, ...]:
        """This branch's records in write order, optionally one actor's.

        Naming any other namespace raises ``NamespaceViolation``: a branch never reads a sibling.
        """

        if namespace is not None and namespace != self.namespace:
            raise NamespaceViolation(f"{self.namespace} read {namespace}")
        with self._lock:
            uuids = list(self._uuids)
        records = []
        for seq, uuid_ in enumerate(uuids):
            body = json.loads(self.client.graph.episode.get(uuid_).content)
            records.append(MemoryRecord(
                self.namespace, body["actor_id"], body["key"], body["value"], body["round"], seq,
            ))
        return tuple(r for r in records if actor_id is None or r.actor_id == actor_id)

    def read(self, actor_id: str, key: str) -> str | None:
        """The latest value this actor stored under ``key``, or None."""

        hits = [r for r in self.retrieve(actor_id=actor_id) if r.key == key]
        return hits[-1].value if hits else None

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(self.world_id, self.branch_id, self.namespace, self.retrieve())
