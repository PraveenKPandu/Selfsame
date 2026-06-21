"""Pull two versions of a module and pair up the functions to check.

Sources can come from two files on disk or two git refs. We match top-level
functions by name, and only pair those whose parameter names are unchanged — a
changed signature is reported separately rather than guessed at.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
