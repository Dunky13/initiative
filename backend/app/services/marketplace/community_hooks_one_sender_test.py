"""Static guard: every hook to a plug-in has one sender.

A hook reaches a plug-in at ``POST {base}/v1/hooks/<name>``, sent by
``plugin_connection_flows.call_hook``. Only ``community_hooks`` calls it, under
the lock it keeps per community and plug-in: the queue's delivery, and
``call_now`` for the hooks whose caller waits on the answer. A second sender
is how a hook came to reach a plug-in after its ``erase``, so these fail when
one appears:

* nothing outside ``community_hooks`` names ``call_hook``;
* the hook address (``HOOKS_PATH``) is used by ``call_hook`` and nothing else;
* no other code spells the hook path out.

The walk is syntactic, like ``app/services/platform/notice_outbox_guard_test.py``.
Docstrings and comments are not read, and ``app/testing`` is the plug-ins'
side, so it is left out.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_APP_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _APP_DIR.parent

_SENDER = "app/services/marketplace/community_hooks.py"
_FLOWS = "app/services/tenant/plugin_connection_flows.py"


def _modules() -> list[tuple[str, ast.Module]]:
    found = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        rel = path.relative_to(_BACKEND_DIR).as_posix()
        if path.name.endswith("_test.py") or rel.startswith("app/testing/"):
            continue
        found.append((rel, ast.parse(path.read_text())))
    return found


class _Uses(ast.NodeVisitor):
    """Where a module reads ``name``: ``path::function`` for the innermost
    function around each read, ``path`` for one at module level."""

    def __init__(self, rel: str, name: str) -> None:
        self.rel, self.name = rel, name
        self.within: list[str] = []
        self.found: set[str] = set()

    def _hit(self) -> None:
        self.found.add("::".join([self.rel, *self.within[-1:]]))

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.within.append(node.name)
        self.generic_visit(node)
        self.within.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.name and not isinstance(node.ctx, ast.Store):
            self._hit()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == self.name and not isinstance(node.ctx, ast.Store):
            self._hit()
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        if self.name in (node.asname, node.name.rsplit(".", 1)[-1]):
            self._hit()


def _uses(name: str) -> set[str]:
    found: set[str] = set()
    for rel, tree in _modules():
        visitor = _Uses(rel, name)
        visitor.visit(tree)
        found |= visitor.found
    return found


def _docstrings(tree: ast.Module) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


def test_only_the_community_hook_queue_calls_call_hook():
    assert _uses("call_hook") == {f"{_SENDER}::_send", f"{_SENDER}::call_now"}, (
        "call_hook is used outside community_hooks' two sends. Queue the hook "
        "(community_hooks.queue_community_hooks), or, for a hook whose answer "
        "the caller waits on, send it with community_hooks.call_now."
    )


def test_the_hook_address_is_used_by_call_hook_alone():
    assert _uses("HOOKS_PATH") == {f"{_FLOWS}::call_hook"}


def test_nothing_else_spells_out_the_hook_path():
    spelled: set[str] = set()
    for rel, tree in _modules():
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
                and "/v1/hooks" in node.value
            ):
                spelled.add(rel)
    assert spelled == {_FLOWS}
