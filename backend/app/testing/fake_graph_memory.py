"""An in-memory stand-in for the hosted graph memory client, namespaced per branch.

It implements the subset of the ``zep_cloud`` client the upstream services call
(``graph_builder``, ``zep_tools``, ``zep_entity_reader``, ``zep_graph_memory_updater``,
``oasis_profile_generator``, ``utils.zep_paging``) and returns the SDK's own response types, so
upstream code reads it unchanged. A method outside that subset does not exist on the fake.

Every graph, node, edge, episode and batch belongs to the namespace that created it
(``world/<world_id>/branch/<branch_id>``). A read or write on something another namespace owns
raises ``NamespaceViolation``; an id nobody owns raises the SDK's ``NotFoundError``. Clients for
sibling namespaces share one ``GraphMemoryStore`` through ``for_namespace``.

The fake does no entity extraction: ``graph.add`` and batch processing store episodes, and a test
seeds the nodes and edges it needs with ``add_node`` and ``add_edge``. Ids are sequential, so a
given sequence of calls always produces the same ids.
"""

from __future__ import annotations

import importlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from zep_cloud import NotFoundError
from zep_cloud.errors import BadRequestError, ConflictError
from zep_cloud.types import (
    ApiError,
    BatchItemDetail,
    BatchItemListResponse,
    BatchListResponse,
    BatchProgress,
    BatchSummary,
    EntityEdge,
    EntityNode,
    Episode,
    Graph,
    GraphSearchResults,
    SuccessResponse,
)

NAMESPACE_RE = re.compile(r"^world/[^/\s]+/branch/[^/\s]+$")
NEXT_CURSOR_HEADER = "zep-next-cursor"
EPOCH = "2026-01-01T00:00:00Z"
# Upstream modules that build their client with ``get_zep_client``; ``install`` points them here.
UPSTREAM_CLIENT_MODULES = (
    "app.services.graph_builder",
    "app.services.zep_tools",
    "app.services.zep_entity_reader",
    "app.services.zep_graph_memory_updater",
    "app.services.oasis_profile_generator",
)


class NamespaceViolation(PermissionError):
    """A graph-memory read or write reached data another namespace owns."""


def namespace_for(world_id: str, branch_id: str) -> str:
    return f"world/{world_id}/branch/{branch_id}"


def _not_found(what: str) -> NotFoundError:
    return NotFoundError(body=ApiError(message=f"{what} not found"))


@dataclass
class _GraphState:
    namespace: str
    graph: Graph
    nodes: dict[str, EntityNode] = field(default_factory=dict)
    edges: dict[str, EntityEdge] = field(default_factory=dict)
    episodes: dict[str, Episode] = field(default_factory=dict)
    ontology: dict[str, Any] | None = None


@dataclass
class _BatchState:
    namespace: str
    summary: BatchSummary
    items: list[tuple[BatchItemDetail, Any]] = field(default_factory=list)


class GraphMemoryStore:
    """The shared state behind every namespace's client."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.graphs: dict[str, _GraphState] = {}
        self.batches: dict[str, _BatchState] = {}
        self.item_graph: dict[str, str] = {}  # node, edge or episode uuid -> graph id
        self._counters: dict[str, int] = {}

    def next_id(self, kind: str) -> str:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        return f"{kind}-{n:06d}"


class FakeGraphMemory:
    """One namespace's view of a ``GraphMemoryStore``, shaped like ``zep_cloud.Zep``."""

    def __init__(self, namespace: str, store: GraphMemoryStore | None = None) -> None:
        if not NAMESPACE_RE.match(namespace):
            raise ValueError(f"namespace must be world/<id>/branch/<id>, got {namespace!r}")
        self.namespace = namespace
        self.store = store if store is not None else GraphMemoryStore()
        self.graph = _GraphClient(self)
        self.batch = _BatchClient(self)

    def for_namespace(self, namespace: str) -> FakeGraphMemory:
        """A client for another namespace over the same store."""

        return FakeGraphMemory(namespace, self.store)

    def install(self, monkeypatch: Any) -> FakeGraphMemory:
        """Make every upstream ``get_zep_client`` call return this client (pytest monkeypatch)."""

        for name in UPSTREAM_CLIENT_MODULES:
            module = importlib.import_module(name)
            monkeypatch.setattr(module, "get_zep_client", lambda *_a, **_k: self)
        return self

    # Ownership checks. Callers hold the store lock.

    def _graph(self, graph_id: str | None) -> _GraphState:
        if not graph_id:
            raise BadRequestError(body=ApiError(message="graph_id is required"))
        state = self.store.graphs.get(graph_id)
        if state is None:
            raise _not_found(f"graph {graph_id}")
        if state.namespace != self.namespace:
            raise NamespaceViolation(
                f"{self.namespace} reached graph {graph_id} owned by {state.namespace}"
            )
        return state

    def _item_graph(self, uuid_: str, kind: str) -> _GraphState:
        graph_id = self.store.item_graph.get(uuid_)
        if graph_id is None or not uuid_.startswith(f"{kind}-"):
            raise _not_found(f"{kind} {uuid_}")
        return self._graph(graph_id)

    def _batch(self, batch_id: str) -> _BatchState:
        state = self.store.batches.get(batch_id)
        if state is None:
            raise _not_found(f"batch {batch_id}")
        if state.namespace != self.namespace:
            raise NamespaceViolation(
                f"{self.namespace} reached batch {batch_id} owned by {state.namespace}"
            )
        return state

    def _new_episode(
        self, state: _GraphState, data: str, *, created_at: str | None,
        source_description: str | None, metadata: dict[str, Any] | None,
    ) -> Episode:
        uuid_ = self.store.next_id("episode")
        episode = Episode(
            uuid_=uuid_, content=data, created_at=created_at or EPOCH, processed=True,
            source_description=source_description, metadata=metadata,
        )
        state.episodes[uuid_] = episode
        self.store.item_graph[uuid_] = state.graph.graph_id
        return episode

    # Seeding: the fake extracts no entities, so tests place the ones they read.

    def add_node(
        self, graph_id: str, name: str, *, labels: list[str] | None = None,
        summary: str = "", attributes: dict[str, Any] | None = None,
    ) -> str:
        with self.store.lock:
            state = self._graph(graph_id)
            uuid_ = self.store.next_id("node")
            state.nodes[uuid_] = EntityNode(
                uuid_=uuid_, name=name, labels=list(labels or ["Entity"]), summary=summary,
                attributes=dict(attributes or {}), created_at=EPOCH,
            )
            self.store.item_graph[uuid_] = graph_id
            return uuid_

    def add_edge(
        self, graph_id: str, source_node_uuid: str, target_node_uuid: str, name: str, fact: str,
        *, attributes: dict[str, Any] | None = None, episodes: list[str] | None = None,
    ) -> str:
        with self.store.lock:
            state = self._graph(graph_id)
            for node_uuid in (source_node_uuid, target_node_uuid):
                if node_uuid not in state.nodes:
                    raise _not_found(f"node {node_uuid} in graph {graph_id}")
            uuid_ = self.store.next_id("edge")
            state.edges[uuid_] = EntityEdge(
                uuid_=uuid_, name=name, fact=fact, source_node_uuid=source_node_uuid,
                target_node_uuid=target_node_uuid, attributes=dict(attributes or {}),
                episodes=list(episodes or []), created_at=EPOCH,
            )
            self.store.item_graph[uuid_] = graph_id
            return uuid_


class _RawResponse:
    def __init__(self, data: Any, headers: dict[str, str]) -> None:
        self.data = data
        self.headers = headers


def _page(items: list[Any], limit: int | None, cursor: str | None) -> tuple[list[Any], str | None]:
    """Cursor pagination over uuid-sorted items; the cursor is the last uuid returned."""

    items = sorted(items, key=lambda item: item.uuid_)
    if cursor is not None:
        items = [item for item in items if item.uuid_ > cursor]
    size = limit if limit is not None else len(items)
    page = items[:size]
    more = len(items) > size and page
    return [item.model_copy(deep=True) for item in page], page[-1].uuid_ if more else None


class _ListByGraph:
    """``get_by_graph_id`` for nodes or edges, plain and ``with_raw_response``."""

    def __init__(self, client: FakeGraphMemory, attr: str) -> None:
        self._client = client
        self._attr = attr

    def _list(self, graph_id: str, limit: int | None, cursor: str | None):
        with self._client.store.lock:
            state = self._client._graph(graph_id)
            return _page(list(getattr(state, self._attr).values()), limit, cursor)

    def get_by_graph_id(self, graph_id: str, *, limit=None, uuid_cursor=None, cursor=None):
        return self._list(graph_id, limit, uuid_cursor or cursor)[0]


class _RawList:
    def __init__(self, lister: _ListByGraph) -> None:
        self._lister = lister

    def get_by_graph_id(self, graph_id: str, *, limit=None, cursor=None) -> _RawResponse:
        data, next_cursor = self._lister._list(graph_id, limit, cursor)
        return _RawResponse(data, {NEXT_CURSOR_HEADER: next_cursor} if next_cursor else {})


class _NodeClient(_ListByGraph):
    def __init__(self, client: FakeGraphMemory) -> None:
        super().__init__(client, "nodes")
        self.with_raw_response = _RawList(self)

    def get(self, uuid_: str) -> EntityNode:
        with self._client.store.lock:
            return self._client._item_graph(uuid_, "node").nodes[uuid_].model_copy(deep=True)

    def get_edges(self, node_uuid: str) -> list[EntityEdge]:
        with self._client.store.lock:
            state = self._client._item_graph(node_uuid, "node")
            return [
                edge.model_copy(deep=True)
                for _, edge in sorted(state.edges.items())
                if node_uuid in (edge.source_node_uuid, edge.target_node_uuid)
            ]


class _EdgeClient(_ListByGraph):
    def __init__(self, client: FakeGraphMemory) -> None:
        super().__init__(client, "edges")
        self.with_raw_response = _RawList(self)

    def get(self, uuid_: str) -> EntityEdge:
        with self._client.store.lock:
            return self._client._item_graph(uuid_, "edge").edges[uuid_].model_copy(deep=True)


class _EpisodeClient:
    def __init__(self, client: FakeGraphMemory) -> None:
        self._client = client

    def get(self, uuid_: str) -> Episode:
        with self._client.store.lock:
            state = self._client._item_graph(uuid_, "episode")
            return state.episodes[uuid_].model_copy(deep=True)


def _score(text: str, terms: set[str]) -> int:
    words = set(re.findall(r"\w+", text.lower()))
    return len(terms & words)


class _GraphClient:
    def __init__(self, client: FakeGraphMemory) -> None:
        self._client = client
        self.node = _NodeClient(client)
        self.edge = _EdgeClient(client)
        self.episode = _EpisodeClient(client)

    def create(self, *, graph_id: str, name: str | None = None, description: str | None = None):
        client = self._client
        with client.store.lock:
            existing = client.store.graphs.get(graph_id)
            if existing is not None:
                if existing.namespace != client.namespace:
                    raise NamespaceViolation(
                        f"{client.namespace} reached graph {graph_id} owned by "
                        f"{existing.namespace}"
                    )
                raise ConflictError(body=ApiError(message=f"graph {graph_id} exists"))
            graph = Graph(
                graph_id=graph_id, name=name, description=description, created_at=EPOCH,
                uuid_=client.store.next_id("graph"),
            )
            client.store.graphs[graph_id] = _GraphState(client.namespace, graph)
            return graph.model_copy(deep=True)

    def get(self, graph_id: str) -> Graph:
        with self._client.store.lock:
            return self._client._graph(graph_id).graph.model_copy(deep=True)

    def delete(self, graph_id: str) -> SuccessResponse:
        store = self._client.store
        with store.lock:
            state = self._client._graph(graph_id)
            for uuid_ in [*state.nodes, *state.edges, *state.episodes]:
                store.item_graph.pop(uuid_, None)
            del store.graphs[graph_id]
            return SuccessResponse(message=f"graph {graph_id} deleted")

    def set_ontology(self, *, graph_ids: list[str], entities=None, edges=None) -> None:
        with self._client.store.lock:
            states = [self._client._graph(graph_id) for graph_id in graph_ids]
            for state in states:
                state.ontology = {"entities": entities, "edges": edges}

    def add(
        self, *, data: str, type: str, graph_id: str | None = None, created_at: str | None = None,
        source_description: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> Episode:
        if type not in {"text", "json", "message"}:
            raise BadRequestError(body=ApiError(message=f"unsupported episode type {type!r}"))
        client = self._client
        with client.store.lock:
            state = client._graph(graph_id)
            episode = client._new_episode(
                state, data, created_at=created_at,
                source_description=source_description, metadata=metadata,
            )
            return episode.model_copy(deep=True)

    def search(
        self, *, query: str, graph_id: str | None = None, limit: int | None = None,
        scope: str | None = None, reranker: str | None = None,
    ) -> GraphSearchResults:
        """Deterministic keyword search: rank by shared words, then by uuid."""

        scope = scope or "edges"
        texts = {
            "edges": lambda e: f"{e.name} {e.fact}",
            "nodes": lambda n: f"{n.name} {n.summary}",
            "episodes": lambda ep: ep.content,
        }
        if scope not in texts:
            raise BadRequestError(body=ApiError(message=f"unsupported search scope {scope!r}"))
        terms = set(re.findall(r"\w+", query.lower()))
        with self._client.store.lock:
            state = self._client._graph(graph_id)
            pool = getattr(state, scope).values()
            scored = [(_score(texts[scope](item), terms), item) for item in pool]
            ranked = sorted(
                ((s, item) for s, item in scored if s > 0), key=lambda p: (-p[0], p[1].uuid_)
            )[: limit or 10]
            hits = [item.model_copy(update={"score": float(s)}, deep=True) for s, item in ranked]
        return GraphSearchResults(**{scope: hits})


class _BatchClient:
    def __init__(self, client: FakeGraphMemory) -> None:
        self._client = client

    def create(self, *, metadata: dict[str, Any] | None = None, ignore_roles=None) -> BatchSummary:
        client = self._client
        with client.store.lock:
            batch_id = client.store.next_id("batch")
            summary = BatchSummary(
                batch_id=batch_id, status="draft", metadata=dict(metadata or {}), item_count=0,
                created_at=EPOCH,
            )
            client.store.batches[batch_id] = _BatchState(client.namespace, summary)
            return summary.model_copy(deep=True)

    def add(self, batch_id: str, *, items: list[Any]) -> list[BatchItemDetail]:
        client = self._client
        with client.store.lock:
            batch = client._batch(batch_id)
            if batch.summary.status != "draft":
                raise BadRequestError(body=ApiError(message=f"batch {batch_id} is not a draft"))
            for item in items:
                if getattr(item, "type", None) != "graph_episode":
                    raise BadRequestError(body=ApiError(message="only graph_episode items"))
                client._graph(item.graph_id)
            added = []
            for item in items:
                detail = BatchItemDetail(
                    item_id=client.store.next_id("item"), kind="graph_episode",
                    graph_id=item.graph_id, sequence_index=len(batch.items), status="pending",
                    created_at=EPOCH,
                )
                batch.items.append((detail, item))
                added.append(detail.model_copy(deep=True))
            batch.summary = batch.summary.model_copy(update={"item_count": len(batch.items)})
            return added

    def process(self, batch_id: str) -> BatchSummary:
        """Ingest every item at once: each becomes a processed episode in its graph."""

        client = self._client
        with client.store.lock:
            batch = client._batch(batch_id)
            if batch.summary.status != "draft":
                raise BadRequestError(body=ApiError(message=f"batch {batch_id} is not a draft"))
            processed = []
            for detail, item in batch.items:
                episode = client._new_episode(
                    client._graph(item.graph_id), item.data or item.content or "",
                    created_at=item.created_at, source_description=item.source_description,
                    metadata=item.metadata,
                )
                update = {"episode_uuid": episode.uuid_, "source_uuid": episode.uuid_,
                          "status": "succeeded"}
                processed.append((detail.model_copy(update=update), item))
            batch.items = processed
            total = len(processed)
            progress = BatchProgress(
                total_items=total, succeeded_items=total, failed_items=0, percent_complete=100.0,
            )
            batch.summary = batch.summary.model_copy(
                update={"status": "succeeded", "progress": progress}
            )
            return batch.summary.model_copy(deep=True)

    def get(self, batch_id: str) -> BatchSummary:
        with self._client.store.lock:
            return self._client._batch(batch_id).summary.model_copy(deep=True)

    def list(self, *, limit: int | None = None, cursor: int | None = None, status=None):
        """This namespace's batches only; the cursor is an offset."""

        client = self._client
        with client.store.lock:
            own = [
                b.summary for _, b in sorted(client.store.batches.items())
                if b.namespace == client.namespace and (status is None or b.summary.status == status)
            ]
        start = cursor or 0
        end = start + (limit or len(own))
        return BatchListResponse(
            batches=[s.model_copy(deep=True) for s in own[start:end]],
            next_cursor=end if end < len(own) else None,
        )

    def list_items(self, batch_id: str, *, limit: int | None = None, cursor: int | None = None,
                   status=None) -> BatchItemListResponse:
        with self._client.store.lock:
            details = [
                d for d, _ in self._client._batch(batch_id).items
                if status is None or d.status == status
            ]
        start = cursor or 0
        end = start + (limit or len(details))
        return BatchItemListResponse(
            items=[d.model_copy(deep=True) for d in details[start:end]],
            next_cursor=end if end < len(details) else None,
        )
