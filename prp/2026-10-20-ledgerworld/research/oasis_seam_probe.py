"""Machine-check of the camel-oasis 0.2.5 dispatch seams listed in oasis-seam.md.

Stdlib only. Downloads the pinned wheels into a temp dir, checks their sha256,
parses the sources with ast and asserts every seam (S1..S13) still has the shape
the research note claims. Also checks that the note's seam table names exactly
the ids and file:symbol pairs checked here, and runs the Python 3.12 scan.

Run: python3 -I prp/2026-10-20-ledgerworld/research/oasis_seam_probe.py
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile
import urllib.request
import warnings
import zipfile

OASIS_WHL = (
    "https://files.pythonhosted.org/packages/77/d0/"
    "6d62173602433937d0228b7809e2b244e09c11cfb1be9c6754ae3b20d887/"
    "camel_oasis-0.2.5-py3-none-any.whl"
)
OASIS_SHA = "9ebd6ba8e331495ee56b25cc63982188b94125dde499e5e9c00398a1d47e606d"
CAMEL_JSON = "https://pypi.org/pypi/camel-ai/0.2.78/json"
CAMEL_SHA = "356624da13dfe0c55ef43dc509c18ce029f67fe3997966495a4ce9be931078d5"
OASIS_JSON = "https://pypi.org/pypi/camel-oasis/0.2.5/json"
NOTE = pathlib.Path(__file__).with_name("oasis-seam.md")
REMOVED_IN_312 = {"distutils", "imp", "asynchat", "asyncore", "smtpd"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def wheel(url: str, sha: str, dest: pathlib.Path, members: str) -> pathlib.Path:
    blob = fetch(url)
    got = hashlib.sha256(blob).hexdigest()
    assert got == sha, f"sha256 mismatch for {url}: {got}"
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.startswith(members) and name.endswith(".py"):
                z.extract(name, dest)
    return dest


class Src:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.trees: dict[str, ast.Module] = {}

    def tree(self, rel: str) -> ast.Module:
        if rel not in self.trees:
            p = self.root / rel
            self.trees[rel] = ast.parse(p.read_text(encoding="utf-8"), rel)
        return self.trees[rel]

    def sym(self, rel: str, qual: str) -> ast.AST:
        node: ast.AST = self.tree(rel)
        for part in qual.split("."):
            found = [
                n for n in getattr(node, "body", [])
                if isinstance(n, (ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef)) and n.name == part
            ]
            assert found, f"{rel}:{qual} — symbol {part!r} missing"
            node = found[0]
        return node


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            fn = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if fn == name:
                out.append(n)
    return out


def inside_try(fn: ast.AST, target: ast.AST) -> bool:
    for t in ast.walk(fn):
        if isinstance(t, ast.Try):
            for stmt in t.body:
                if any(n is target for n in ast.walk(stmt)):
                    return True
    return False


def src_text(node: ast.AST) -> str:
    return ast.unparse(node)


# Each seam: id -> (file, symbol, check(src, node)). The check asserts the
# shape the note relies on; a release that changes it fails here first.
def s1(s, n):
    names = [t.id for st in n.body if isinstance(st, ast.Assign)
             for t in st.targets if isinstance(t, ast.Name)]
    assert [b.id for b in n.bases] == ["Enum"] and names, "ActionType not an Enum with members"
    assert "DISBURSE" not in names and "PAY" not in names


def s2(s, n):
    coerce = calls(n, "ActionType")
    assert coerce, "running() no longer coerces with ActionType(...)"
    assert not any(isinstance(t, ast.Try) for t in ast.walk(n)), "running() now catches"
    assert "co_argcount" in src_text(n), "running() no longer introspects __code__"


def s3(s, n):
    text = src_text(n)
    for name in ("self.purchase_product", "self.interview", "self.do_nothing"):
        assert name in text, f"{name} left the fixed tool list"
    assert "self.sign_up" not in text


def s4(s, n):
    text = src_text(n)
    assert "self.env = SocialEnvironment(SocialAction(" in text, "env is now injectable"
    assert "all_tools = (tools or []) + (self.action_tools or [])" in text
    assert "if not available_actions:" in text, "empty available_actions no longer means all"
    body = [src_text(st) for st in n.body]
    sup = next((i for i, t in enumerate(body) if t.startswith("super().__init__(")), None)
    mi = next((i for i, t in enumerate(body) if t == "self.max_iteration = max_iteration"), None)
    assert sup is not None and mi is not None and mi > sup, \
        "max_iteration no longer set after ChatAgent.__init__"
    assert "max_iteration" not in src_text(n.body[sup])


def s5(s, n):
    assert calls(n, "to_text_prompt"), "prompt no longer from env.to_text_prompt"
    handlers = [h for t in ast.walk(n) if isinstance(t, ast.Try) for h in t.handlers]
    assert any(isinstance(st, ast.Return) and isinstance(st.value, ast.Name)
               and st.value.id == h.name for h in handlers for st in h.body), \
        "exceptions are no longer returned as values"


def s6(s, n):
    assert calls(n, "get_openai_function_list")
    assert any(isinstance(t, ast.Raise) for t in ast.walk(n))


def s7(s, n):
    sub = [t for t in ast.walk(n) if isinstance(t, ast.Subscript)
           and "_internal_tools" in src_text(t.value)]
    assert sub and not inside_try(n, sub[0]), "unknown tool lookup is now guarded"
    handlers = [h for t in ast.walk(n) if isinstance(t, ast.Try) for h in t.handlers]
    assert any("Tool execution failed" in src_text(h) for h in handlers), \
        "tool exceptions no longer become a string result"


def s8(s, n):
    assert "_internal_tools" in src_text(n)


def s9(s, n):
    text = src_text(n)
    assert "clock" not in text and "time" not in text, "observation now time-scoped"


def s10(s, n):
    g = calls(n, "gather")
    assert g and not any(k.arg == "return_exceptions" for k in g[0].keywords)
    incr = [t for t in ast.walk(n) if isinstance(t, ast.If)
            and "TWITTER" in src_text(t.test)
            and "time_step += 1" in src_text(t)]
    assert incr, "clock advance no longer limited to TWITTER"


def s11(s, n):
    text = src_text(n)
    assert "isinstance(platform, Platform)" in text
    assert "platform.recsys_type == RecsysType.REDDIT" in text


def s12(s, n):
    init = s.sym("oasis/clock/clock.py", "Clock.__init__")
    assert "datetime.now()" in src_text(init), "Clock no longer wall-clock based"


def s13(s, n):
    mod = s.tree("oasis/social_agent/agents_generator.py")
    gens = [f for f in mod.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and f.name.startswith("generate_") and calls(f, "SocialAgent")]
    assert len(gens) >= 3, "generators no longer hard-code SocialAgent(...)"
    env = s.tree("oasis/environment/env.py")
    top = [st for st in env.body if isinstance(st, ast.If)]
    assert any(calls(st, "makedirs") for st in top), "./log side effect gone"


SEAMS = {
    "S1": ("oasis/social_platform/typing.py", "ActionType", s1),
    "S2": ("oasis/social_platform/platform.py", "Platform.running", s2),
    "S3": ("oasis/social_agent/agent_action.py", "SocialAction.get_openai_function_list", s3),
    "S4": ("oasis/social_agent/agent.py", "SocialAgent.__init__", s4),
    "S5": ("oasis/social_agent/agent.py", "SocialAgent.perform_action_by_llm", s5),
    "S6": ("oasis/social_agent/agent.py", "SocialAgent.perform_action_by_data", s6),
    "S7": ("camel/agents/chat_agent.py", "ChatAgent._aexecute_tool", s7),
    "S8": ("camel/agents/chat_agent.py", "ChatAgent.add_tool", s8),
    "S9": ("oasis/social_agent/agent_environment.py", "SocialEnvironment.to_text_prompt", s9),
    "S10": ("oasis/environment/env.py", "OasisEnv.step", s10),
    "S11": ("oasis/environment/env.py", "OasisEnv.__init__", s11),
    "S12": ("oasis/clock/clock.py", "Clock.time_transfer", s12),
    "S13": ("oasis/social_agent/agents_generator.py", "generate_twitter_agent_graph", s13),
}


def check_note() -> None:
    rows = re.findall(r"^\| (S\d+) \| `([^`]+):([^`]+)` \|", NOTE.read_text(encoding="utf-8"), re.M)
    in_note = {i: (f, q) for i, f, q in rows}
    in_probe = {i: (f, q) for i, (f, q, _) in SEAMS.items()}
    assert in_note == in_probe, f"note table and probe disagree:\n{in_note}\n{in_probe}"


def check_312(root: pathlib.Path) -> list[str]:
    report = []
    meta = json.loads(fetch(OASIS_JSON))
    report.append(f"camel-oasis 0.2.5 requires_python = {meta['info']['requires_python']!r}")
    for p in sorted((root / "oasis").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(text, str(p), "exec")
        for n in ast.walk(ast.parse(text)):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module.split(".")[0]]
            bad = REMOVED_IN_312.intersection(mods)
            assert not bad, f"{p.relative_to(root)} imports {bad} (removed in 3.12)"
            assert "unstructured" not in mods, f"{p} imports unstructured (<3.12 only)"
        assert "get_event_loop" not in text, f"{p} uses asyncio.get_event_loop"
    report.append(f"oasis sources compile clean on Python {sys.version.split()[0]} "
                  "(SyntaxWarning=error); no distutils/imp/asyncore/asynchat/smtpd, "
                  "no get_event_loop, no unstructured import")
    return report


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="oasis-seam-"))
    try:
        wheel(OASIS_WHL, OASIS_SHA, tmp, "oasis/")
        camel = json.loads(fetch(CAMEL_JSON))
        url = next(u["url"] for u in camel["urls"] if u["filename"].endswith(".whl"))
        wheel(url, CAMEL_SHA, tmp, "camel/agents/chat_agent.py")
        src = Src(tmp)
        for sid, (rel, qual, check) in SEAMS.items():
            check(src, src.sym(rel, qual))
            print(f"ok {sid} {rel}:{qual}")
        check_note()
        print(f"ok note table matches {len(SEAMS)} seams")
        for line in check_312(tmp):
            print(f"ok {line}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
