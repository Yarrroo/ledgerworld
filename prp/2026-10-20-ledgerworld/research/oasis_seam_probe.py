"""Machine-check of the camel-oasis 0.2.5 dispatch seams listed in oasis-seam.md.

Stdlib only. Downloads the pinned wheels into a temp dir, checks their sha256,
parses the sources with ast and asserts every seam (S1..S13) still has the shape
the research note claims. Also checks that the note's seam table names exactly
the ids and file:symbol pairs checked here, and runs the Python 3.12 scan.
Checks raise explicitly, so `python -O` cannot strip them.

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
CAMEL_WHL = (
    "https://files.pythonhosted.org/packages/01/81/"
    "0cfb1c0d9da589665e2eb4471887967e70bba428638c37fb4f6a78baf300/"
    "camel_ai-0.2.78-py3-none-any.whl"
)
CAMEL_SHA = "356624da13dfe0c55ef43dc509c18ce029f67fe3997966495a4ce9be931078d5"
OASIS_JSON = "https://pypi.org/pypi/camel-oasis/0.2.5/json"
CAMEL_JSON = "https://pypi.org/pypi/camel-ai/0.2.78/json"
NOTE = pathlib.Path(__file__).with_name("oasis-seam.md")
REMOVED_IN_312 = {"distutils", "imp", "asynchat", "asyncore", "smtpd"}


class ProbeFailure(AssertionError):
    pass


def check(cond: object, msg: str) -> None:
    if not cond:
        raise ProbeFailure(msg)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def wheel(url: str, sha: str, dest: pathlib.Path, members: str) -> None:
    blob = fetch(url)
    got = hashlib.sha256(blob).hexdigest()
    check(got == sha, f"sha256 mismatch for {url}: {got}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.startswith(members) and name.endswith(".py"):
                z.extract(name, dest)


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
            check(found, f"{rel}:{qual} — symbol {part!r} missing")
            node = found[0]
        return node


def call_name(c: ast.Call) -> str | None:
    f = c.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and call_name(n) == name]


def inside_try(fn: ast.AST, target: ast.AST) -> bool:
    for t in ast.walk(fn):
        if isinstance(t, ast.Try):
            for stmt in t.body:
                if any(n is target for n in ast.walk(stmt)):
                    return True
    return False


def handlers(fn: ast.AST) -> list[ast.ExceptHandler]:
    return [h for t in ast.walk(fn) if isinstance(t, ast.Try) for h in t.handlers]


def src_text(node: ast.AST) -> str:
    return ast.unparse(node)


# Each seam: id -> (file, symbol, check(src, node)). The check asserts the
# shape the note relies on; a release that changes it fails here first.
def s1(s, n):
    names = [t.id for st in n.body if isinstance(st, ast.Assign)
             for t in st.targets if isinstance(t, ast.Name)]
    check([b.id for b in n.bases] == ["Enum"] and names, "ActionType not an Enum with members")
    check("DISBURSE" not in names and "PAY" not in names, "ActionType grew finance members")


def s2(s, n):
    coerce = calls(n, "ActionType")
    check(coerce, "running() no longer coerces with ActionType(...)")
    check(not any(inside_try(n, c) for c in coerce), "ActionType(...) coercion is now guarded")
    check("if len_param_names > 3:" in src_text(n), "handler arity limit is no longer 3")


def s3(s, n):
    text = src_text(n)
    tools = re.findall(r"self\.(\w+)", text)
    check(len(tools) == 29, f"social tool list is {len(tools)}, not 29")
    for name in ("purchase_product", "interview", "do_nothing"):
        check(name in tools, f"{name} left the fixed tool list")
    check("sign_up" not in tools, "sign_up joined the tool list")


def s4(s, n):
    text = src_text(n)
    check("self.env = SocialEnvironment(SocialAction(" in text, "env is now injectable")
    check("all_tools = (tools or []) + (self.action_tools or [])" in text, "tools= no longer concatenated")
    check("if not available_actions:" in text, "empty available_actions no longer means all")
    body = [src_text(st) for st in n.body]
    sup = next((i for i, t in enumerate(body) if t.startswith("super().__init__(")), None)
    mi = next((i for i, t in enumerate(body) if t == "self.max_iteration = max_iteration"), None)
    check(sup is not None and mi is not None and mi > sup,
          "max_iteration no longer set after ChatAgent.__init__")
    check("max_iteration" not in body[sup], "max_iteration now passed to ChatAgent")


def s5(s, n):
    check(calls(n, "to_text_prompt"), "prompt no longer from env.to_text_prompt")
    check(any(isinstance(st, ast.Return) and isinstance(st.value, ast.Name)
              and st.value.id == h.name for h in handlers(n) for st in h.body),
          "exceptions are no longer returned as values")


def s6(s, n):
    check(calls(n, "get_openai_function_list"), "ManualAction no longer searches SocialAction")
    check(any(isinstance(t, ast.Raise) for t in ast.walk(n)), "unknown name no longer raises")


def s7(s, n):
    subs = [t for t in ast.walk(n) if isinstance(t, ast.Subscript)
            and "_internal_tools" in src_text(t.value)]
    check(subs and not any(inside_try(n, t) for t in subs), "unknown tool lookup is now guarded")
    check("_internal_tools.get(" not in src_text(n), "tool lookup now uses .get()")
    check(any("Tool execution failed" in src_text(h) for h in handlers(n)),
          "tool exceptions no longer become a string result")


def s8(s, n):
    check("_internal_tools" in src_text(n), "add_tool no longer registers an executable tool")
    s.sym("camel/agents/chat_agent.py", "ChatAgent.add_external_tool")


def s9(s, n):
    used = {call_name(c) for c in ast.walk(n) if isinstance(c, ast.Call)}
    expected = {"get_followers_env", "get_follows_env", "get_posts_env",
                "get_group_env", "substitute"}
    check(used == expected, f"to_text_prompt now calls {sorted(used - expected)} — re-read for scoping")


def s10(s, n):
    g = calls(n, "gather")
    check(g and not any(k.arg == "return_exceptions" for k in g[0].keywords),
          "gather now sets return_exceptions")
    incr = [t for t in ast.walk(n) if isinstance(t, ast.If)
            and "TWITTER" in src_text(t.test)
            and "time_step += 1" in src_text(t)]
    check(incr, "clock advance no longer limited to TWITTER")


def s11(s, n):
    text = src_text(n)
    check("isinstance(platform, Platform)" in text, "custom Platform instance no longer accepted")
    check("platform.recsys_type == RecsysType.REDDIT" in text, "platform type no longer from recsys_type")


def s12(s, n):
    check("self.k" in src_text(n), "time_transfer no longer scales by k")
    init = s.sym("oasis/clock/clock.py", "Clock.__init__")
    check("datetime.now()" in src_text(init), "Clock no longer wall-clock based")


def s13(s, n):
    mod = s.tree("oasis/social_agent/agents_generator.py")
    built = {call_name(c) for f in mod.body
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             for c in ast.walk(f) if isinstance(c, ast.Call)
             and (call_name(c) or "").endswith("Agent")}
    check(built == {"SocialAgent"}, f"generators now build {built}")
    check(calls(n, "SocialAgent"), "generate_twitter_agent_graph no longer builds SocialAgent")
    env = s.tree("oasis/environment/env.py")
    check(any(calls(st, "makedirs") for st in env.body if isinstance(st, ast.If)),
          "env.py no longer creates ./log at import")
    agent = s.tree("oasis/social_agent/agent.py")
    check(any(calls(st, "FileHandler") for st in agent.body if isinstance(st, ast.If)),
          "agent.py no longer opens a log file at import")
    recsys = s.tree("oasis/social_platform/recsys.py")
    check(any(isinstance(st, ast.Import) and st.names[0].name == "torch" for st in recsys.body),
          "recsys no longer imports torch at module level")
    plat = s.tree("oasis/social_platform/platform.py")
    check(any(isinstance(st, ast.ImportFrom) and st.module == "oasis.social_platform.recsys"
              for st in plat.body), "platform no longer imports recsys at module level")


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


def check_note(note: pathlib.Path = NOTE) -> None:
    text = note.read_text(encoding="utf-8")
    seam_lines = re.findall(r"^\|\s*\**S\d+\b.*$", text, re.M)
    rows = re.findall(r"^\| (S\d+) \| `([^`]+):([^`]+)` \|", text, re.M)
    check(len(rows) == len(seam_lines), "a seam row in the note is not in `| Sn | `file:sym` |` form")
    ids = [i for i, _, _ in rows]
    check(len(ids) == len(set(ids)), f"duplicate seam ids in the note: {ids}")
    in_note = sorted(rows)
    in_probe = sorted((i, f, q) for i, (f, q, _) in SEAMS.items())
    check(in_note == in_probe, f"note table and probe disagree:\n{in_note}\n{in_probe}")


def check_312(root: pathlib.Path) -> list[str]:
    check(sys.version_info[:2] >= (3, 12), f"the 3.12 scan needs Python >= 3.12, got {sys.version.split()[0]}")
    report = []
    oasis_rp = json.loads(fetch(OASIS_JSON))["info"]["requires_python"]
    check(oasis_rp == "<3.12,>=3.10.0", f"camel-oasis requires_python changed: {oasis_rp!r}")
    camel_rp = json.loads(fetch(CAMEL_JSON))["info"]["requires_python"]
    check(camel_rp == "<3.13,>=3.10", f"camel-ai requires_python changed: {camel_rp!r}")
    report.append(f"requires_python: camel-oasis {oasis_rp!r}, camel-ai {camel_rp!r}")
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
            check(not bad, f"{p.relative_to(root)} imports {bad} (removed in 3.12)")
            check("unstructured" not in mods, f"{p} imports unstructured (<3.12 only)")
        check("get_event_loop" not in text, f"{p} uses asyncio.get_event_loop")
    report.append(f"oasis sources compile clean on Python {sys.version.split()[0]} "
                  "(SyntaxWarning=error); no distutils/imp/asyncore/asynchat/smtpd, "
                  "no get_event_loop, no unstructured import")
    return report


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="oasis-seam-"))
    try:
        wheel(OASIS_WHL, OASIS_SHA, tmp, "oasis/")
        wheel(CAMEL_WHL, CAMEL_SHA, tmp, "camel/agents/chat_agent.py")
        src = Src(tmp)
        for sid, (rel, qual, fn) in SEAMS.items():
            fn(src, src.sym(rel, qual))
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
