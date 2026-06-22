"""Pull two versions of a module and pair up the functions to check.

Sources can come from two files on disk or two git refs. We match top-level
functions by name, and only pair those whose parameter names are unchanged — a
changed signature is reported separately rather than guessed at.
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List


def source_from_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def source_from_git(ref: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", "%s:%s" % (ref, path)], text=True)


def _functions(src: str) -> Dict[str, ast.FunctionDef]:
    tree = ast.parse(src)
    out: Dict[str, ast.FunctionDef] = {}
    for node in tree.body:  # top-level only (methods are out of scope for v0.1)
        if isinstance(node, ast.FunctionDef):
            out[node.name] = node
    return out


def _param_names(fn: ast.FunctionDef) -> List[str]:
    a = fn.args
    return [p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)]


@dataclass
class Pairing:
    matched: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    sig_changed: List[str] = field(default_factory=list)


def pair_functions(before_src: str, after_src: str) -> Pairing:
    before = _functions(before_src)
    after = _functions(after_src)
    p = Pairing()
    for name in sorted(set(before) & set(after)):
        if _param_names(before[name]) == _param_names(after[name]):
            p.matched.append(name)
        else:
            p.sig_changed.append(name)
    p.added = sorted(set(after) - set(before))
    p.removed = sorted(set(before) - set(after))
    return p


# Modules / calls that mean a function can touch the uncontrolled outside world.
# Runtime counting (probe.harness) catches I/O that the sampled inputs actually
# reach; this static scan catches I/O hiding behind inputs we never generated
# (e.g. urlopen on a garbage string fails at URL parsing, before any socket).
_IO_MODULES = ("socket", "ssl", "urllib", "http", "requests", "httpx",
               "ftplib", "smtplib", "telnetlib", "subprocess")
_IO_CALL_NAMES = {"open", "urlopen", "urlretrieve"}
_IO_ATTR_NAMES = {"urlopen", "urlretrieve", "system", "popen", "Popen",
                  "check_output", "check_call", "connect"}


def io_capability(src: str, name: str):
    """Return a reason string if function `name` can perform uncontrolled I/O,
    else None. Conservative: prefers a false refusal over false confidence."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    for a in sub.names:
                        if a.name.split(".")[0] in _IO_MODULES:
                            return "imports %s" % a.name
                elif isinstance(sub, ast.ImportFrom):
                    if sub.module and sub.module.split(".")[0] in _IO_MODULES:
                        return "imports from %s" % sub.module
                elif isinstance(sub, ast.Call):
                    f = sub.func
                    if isinstance(f, ast.Name) and f.id in _IO_CALL_NAMES:
                        return "calls %s()" % f.id
                    if isinstance(f, ast.Attribute) and f.attr in _IO_ATTR_NAMES:
                        return "calls .%s()" % f.attr
            return None
    return None


def _path_to_module(path: str) -> str:
    p = path
    if p.startswith("src/"):
        p = p[4:]
    if p.endswith("/__init__.py"):
        p = p[: -len("/__init__.py")]
    elif p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def _func_segments(src: str):
    """{qualname: source} for top-level functions AND methods (Class.method)."""
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out

    def visit(node, prefix):
        for child in getattr(node, "body", []):
            if isinstance(child, ast.FunctionDef):
                seg = ast.get_source_segment(src, child)
                out[prefix + child.name] = seg if seg is not None else ast.dump(child)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")

    visit(tree, "")
    return out


def changed_keys(repo: str, base: str, head: str):
    """Set of 'module::qualname' for functions/methods whose body changed between
    base and head (head == 'WORKTREE' compares against the working tree)."""
    if head == "WORKTREE":
        diff = ["diff", "--name-only", base, "--", "*.py"]
    else:
        diff = ["diff", "--name-only", base, head, "--", "*.py"]
    try:
        files = subprocess.check_output(["git", "-C", repo] + diff, text=True).split()
    except subprocess.CalledProcessError:
        return set()

    keys = set()
    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            base_src = subprocess.check_output(
                ["git", "-C", repo, "show", "%s:%s" % (base, f)],
                text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            base_src = ""
        if head == "WORKTREE":
            try:
                with open(os.path.join(repo, f)) as fh:
                    head_src = fh.read()
            except OSError:
                head_src = ""
        else:
            try:
                head_src = subprocess.check_output(
                    ["git", "-C", repo, "show", "%s:%s" % (head, f)],
                    text=True, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                head_src = ""
        base_segs, head_segs = _func_segments(base_src), _func_segments(head_src)
        mod = _path_to_module(f)
        for qn in set(base_segs) | set(head_segs):
            if base_segs.get(qn) != head_segs.get(qn):
                keys.add(mod + "::" + qn)
    return keys


def build_function(src: str, name: str):
    """Exec a module source in a fresh namespace and return one function.

    Runs module-level code (imports, helpers, class defs) so the function has its
    real globals. Intended to run inside an isolated worker process.
    """
    ns: Dict[str, object] = {"__name__": "_probe_extracted"}
    exec(compile(src, "<extracted>", "exec"), ns)
    fn = ns.get(name)
    if not callable(fn):
        raise ValueError("'%s' is not a callable in the module" % name)
    return fn
