"""Finance extensions of camel-oasis, by subclassing and registration.

The tool boundary: an actor changes financial state only by calling its finance tools, each of
which queues one C1 intent on its branch's queue (``actions``); it sees only its scoped
observation (``observation``); a malformed response gets one repair, then ``no_action`` and an
alert (``guardrail``). Clearing the queued intents against the ledger is the coordinator's.
"""

from oasis_finance.actions import (
    FinanceActor,
    FinancialActionType,
    IntentQueue,
    ToolCallError,
    Turn,
    make_finance_tools,
    parse_tool_call,
    submit,
    tool_schema,
)
from oasis_finance.guardrail import (
    Alert,
    RawCall,
    TurnResult,
    amodel_responder,
    arun_turn,
    model_responder,
    repair_marker,
    run_turn,
)
from oasis_finance.observation import Observation, build_observation, canonical_json, sha256_of

__all__ = [
    "Alert",
    "FinanceActor",
    "FinancialActionType",
    "IntentQueue",
    "Observation",
    "RawCall",
    "ToolCallError",
    "Turn",
    "TurnResult",
    "amodel_responder",
    "arun_turn",
    "build_observation",
    "canonical_json",
    "make_finance_tools",
    "model_responder",
    "parse_tool_call",
    "repair_marker",
    "run_turn",
    "sha256_of",
    "submit",
    "tool_schema",
]
