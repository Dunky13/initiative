"""In-app MCP server.

Mounted at ``/api/v1/mcp/`` only when ``settings.ENABLE_MCP`` is set. Tools are
*route-backed*: each call flows through the real FastAPI route, so the PAT
authentication and the six RLS gates apply by reuse — never re-implemented.

The surface is curated and default-deny, so a newly added route can't silently
become a tool:
  * **Reads** — every ``GET`` route for initiatives and for the tools they hold
    (projects and tasks, files, queues, counters, calendars and their
    events, wikis and their pages, notices, dashboards), plus the two comment
    reads that pair with the comment write (a parent's thread and a single
    comment by id), plus the one relationships read, which answers what a thing
    is linked to, plus the guild's general search, which finds a thing by name. A handful are carved back out: file downloads, who voted and
    who has read, and the dashboard editor's own palette.
  * **Writes** — an explicit allow-list, matched by path shape: create and edit
    every tool (projects, files, queues, counters, calendars, wikis,
    notices, dashboards) and the things they hold (tasks, queue items, counters,
    calendar events, wiki pages, comments), plus the two writes that shape alone
    doesn't reach — moving a task, and moving a counter's count — plus drawing
    one relationship between two of them. Each is gated client-side by Claude Code's
    per-write permission prompt. Destructive (delete, archive, reset), bulk
    (reorder, batch, archive-all, replacing a thing's links wholesale),
    AI-generation, sharing (grants), and property/tag routes are deliberately
    excluded. A tool's create still takes its initial ``grants``, as it does in
    the app: who a new thing is shared with is part of making it.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.openapi.models import HTTPRoute

from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.config import PROJECT_NAME
from app.core.tools import Tool

if TYPE_CHECKING:
    import mcp.types as mt
    from fastapi import FastAPI

# Read surface: every GET route carrying these FastAPI tags becomes a tool.
# ``task-statuses`` exposes only its GET (list a project's statuses) — its
# POST/PATCH/reorder routes aren't in the write allow-list, so they stay
# excluded — giving a caller the status ids needed to place or move a task.
#
# Every tool an initiative holds is readable, not only the two it starts with.
# An agent asked "how is this going" was previously answering from tasks alone,
# which is the shape of the question rather than the shape of the work: the
# rota is a queue, the write-up is a file, the numbers are counters, and
# what somebody would actually look at first is a dashboard. The write surface
# in ``_WRITE_ROUTE_MAPS`` covers the same set, so what an agent can read it can
# also author and edit.
READ_TAGS = (
    # Every tool's own tag, as its list is published under.
    *(TOOL_LISTS[tool].tag or tool.plural for tool in Tool),
    "tasks",
    "initiatives",
    "task-statuses",
    "calendar-events",
    # A window of a calendar: its events, a repeating one expanded into its
    # occurrences, beside the tasks due in it. The events have no list of
    # their own; this is what "what's on this week" reads.
    "calendar-entries",
    # How many of each a page holds, and its tag tree: counted from the lists
    # above, for every tool at once.
    "tools",
)

# Curated writes: author and edit, across every tool.
#
# Matched by exact path *shape*, so only the pairs named here are exposed and
# everything else falls through to the default-deny catch-all below — delete,
# archive, reorder, duplicate, batch, AI generation, grants, properties/tags,
# uploads and imports are all outside it.
#
# The tool half is derived from the ``Tool`` enum rather than listed, for the
# same reason the read surface is: an eighth tool should arrive writable rather
# than wait for somebody to remember this list. ``counter_group`` is the only
# member whose path segment isn't already its plural spelling.
_ID = r"\{[^}]+\}"


def _create_and_edit(created_at: str, edited_at: str) -> list[RouteMap]:
    """The two route shapes that author and edit one kind of thing.

    ``POST /<created_at>`` creates and ``PATCH /<edited_at>/{id}`` edits. Both
    are anchored at the end, so a suffixed route on the same collection — an
    ``/archive``, a ``/grants``, a ``/properties``, a ``/reorder`` — matches
    neither and stays excluded.
    """
    return [
        RouteMap(
            methods=["POST"],
            pattern=r".*/" + created_at + r"/?$",
            mcp_type=MCPType.TOOL,
        ),
        RouteMap(
            methods=["PATCH"],
            pattern=r".*/" + edited_at + "/" + _ID + "$",
            mcp_type=MCPType.TOOL,
        ),
    ]


_WRITABLE_SEGMENTS = (
    # Every tool an initiative holds, addressed by its own path segment.
    *((tool.route_segment, tool.route_segment) for tool in Tool),
    # And what those tools hold in turn: a project's tasks, a calendar's
    # events, a queue's items, a counter group's counters, a wiki's pages. Not
    # derivable from the enum — each names its parent differently — so each is
    # spelled out. Tasks and events name their parent in the body; the other
    # three are added under it, and edited at their own id like the rest.
    ("tasks", "tasks"),
    ("calendar-events", "calendar-events"),
    ("queues/" + _ID + "/items", "queue-items"),
    ("counter-groups/" + _ID + "/counters", "counters"),
    ("wikis/" + _ID + "/pages", "wiki-pages"),
    # The comment surface every tool shares.
    ("comments", "comments"),
)

# Two writes that ``create``/``edit`` doesn't reach, added by hand:
#
#   * Moving a task to another status or project is its own route because it is
#     its own action, taking a destination rather than a field.
#   * A counter's count is the one thing about it ``PATCH`` cannot set — the
#     update schema shapes the counter (name, bounds, step, initial count) and
#     the count itself moves through these two. Without them, writing a
#     counter would mean renaming it. ``reset`` and ``reset-all`` are not here:
#     they discard counts rather than record one.
#   * Ticking one checklist item. ``PATCH /tasks/{id}`` rewrites the list's
#     lines but deliberately never its ``done`` flags, so without this an agent
#     that finished a piece of a task could say so only in a comment. It names
#     one item and touches only that one, the same write the app's checkbox
#     makes.
_EXTRA_WRITE_ROUTE_MAPS = [
    RouteMap(
        methods=["POST"], pattern=r".*/tasks/" + _ID + "/move$", mcp_type=MCPType.TOOL
    ),
    RouteMap(
        methods=["PATCH"],
        pattern=r".*/tasks/" + _ID + "/checklist/" + _ID + "$",
        mcp_type=MCPType.TOOL,
    ),
    *(
        RouteMap(
            methods=["POST"],
            pattern=r".*/counters/" + _ID + "/" + verb + "$",
            mcp_type=MCPType.TOOL,
        )
        for verb in ("set", "step")
    ),
]

_WRITE_ROUTE_MAPS = [
    *(m for segments in _WRITABLE_SEGMENTS for m in _create_and_edit(*segments)),
    *_EXTRA_WRITE_ROUTE_MAPS,
]

# Comment reads, matched by exact path shape rather than by adding ``comments``
# to ``READ_TAGS``, so only these two of the router's four GETs are exposed:
# list a parent's thread (``GET /comments/``) and read one comment back by id
# (``GET /comments/{id}``). Together they close the loop on the comment write —
# an agent can see the discussion on the task it is working and read back what
# it posted in a later session.
#
# The other two stay behind the default-deny catch-all. ``GET /comments/recent``
# is a guild-wide activity feed rather than a working surface — the same reason
# ``join-requests`` is carved out of the ``initiatives`` tag — and it reaches
# comments on parents (files, queues, counters, calendars, dashboards) that
# the tool surface otherwise doesn't cover, undirected by any task at hand.
# ``GET /comments/mentions/search`` backs the editor's @-mention picker; the
# member and task lookups an agent needs are already tools of their own.
_COMMENT_READ_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/comments/$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["GET"], pattern=r".*/comments/\{[^}]+\}$", mcp_type=MCPType.TOOL),
]

# The guild's general search: how a caller reaches a thing it knows the name of
# rather than the id of. Matched by path shape rather than by adding ``search``
# to ``READ_TAGS``, for the same reason the comment reads are — the router's
# other two GETs answer for a *picker* rather than for a question. ``recent``
# is what a field offers before anything is typed and ``suggest`` is titles to
# jump to while it is being typed; both describe a text input's behaviour. The
# search proper is the one an agent wants: ranked, narrowable by entity type
# and initiative, and carrying a ``total``, so "find the task called X" is one
# call instead of a guess at a filter.
_SEARCH_READ_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/search/$", mcp_type=MCPType.TOOL),
]

# The edges between the things above: read them, and draw one.
#
# Matched by path shape rather than by a tag or a ``_WRITABLE_SEGMENTS`` entry,
# for the same reason the comment reads are — a relationship is not a tool an
# initiative holds, and the router's four routes divide two and two, so each
# side is named rather than opted into wholesale.
#
# ``GET /relationships/`` answers what no tool read can: a task's payload
# carries its status, its people and its tags, but nothing about the task it
# blocks, the file it was written from, or the queue item it came out of —
# and that wiring is most of what "what is the state of this" means once a piece
# of work touches more than one tool. It answers for one thing at a time
# (``entity=task:12``), from that thing's side.
#
# ``POST /relationships/`` is the same create-and-edit reasoning the tool writes
# follow: what an agent can read it can also author, and an agent that files a
# task and writes the file behind it should be able to say so. There is no
# PATCH to pair with it — an edge has no fields to edit, only ends and a type,
# which are what it *is* — so the create stands alone. The endpoint refuses the
# links that aren't anybody's to assert by hand (a ``references`` edge is read
# out of a body when it is saved), ends in different initiatives, archived ends,
# and a source the caller can't write; none of that is re-implemented here.
#
# The router's other two stay behind the default-deny catch-all, on the grounds
# every other write is weighed against: ``PUT /relationships/`` replaces a whole
# slice of one thing's links, which is bulk *and* removes what it doesn't
# mention, and ``DELETE /relationships/{id}`` is a delete. An agent can wire two
# things together; unwiring them is done in the app.
_RELATIONSHIP_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r".*/relationships/$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r".*/relationships/$", mcp_type=MCPType.TOOL),
]

# Carved out of the tag rules below, each for a reason the tag itself cannot
# express. Ordered ahead of them so the exclusion wins.
_TOOL_READ_EXCLUSIONS = [
    # Bytes rather than an answer. A download hands back a file — an uploaded file's
    # contents, or one of its versions — and an export hands back a calendar
    # file. Neither is something a tool result can carry usefully, and a large
    # one would fill a caller's context with an attachment it cannot open.
    RouteMap(pattern=r".*/download$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/export\.ics$", mcp_type=MCPType.EXCLUDE),
    # Who voted which way, and who has read a notice. Both are about people
    # rather than about the work, and neither is answerable from the thing an
    # agent was asked to do — the same reason join requests are carved out of
    # the initiatives tag.
    RouteMap(pattern=r".*/poll/voters$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/reads$", mcp_type=MCPType.EXCLUDE),
    # The editor's own vocabulary. ``widget-catalog`` is the palette a person
    # arranges a dashboard from and ``installed-listings`` is what the
    # marketplace has put in this guild; both describe the authoring surface
    # rather than anything a dashboard is showing.
    RouteMap(pattern=r".*/widget-catalog$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r".*/installed-listings$", mcp_type=MCPType.EXCLUDE),
]

_ROUTE_MAPS = [
    *_WRITE_ROUTE_MAPS,
    *_COMMENT_READ_ROUTE_MAPS,
    *_SEARCH_READ_ROUTE_MAPS,
    *_RELATIONSHIP_ROUTE_MAPS,
    *_TOOL_READ_EXCLUSIONS,
    # Carved out of the ``initiatives`` read surface below: a join request names
    # who asked to be let in and carries their free-text note, which is
    # membership administration for a manager to answer rather than part of the
    # project/task surface these tools serve. Ordered ahead of the tag rule so
    # the exclusion wins.
    RouteMap(pattern=r".*/join-requests.*", mcp_type=MCPType.EXCLUDE),
    *(
        RouteMap(methods=["GET"], tags={tag}, mcp_type=MCPType.TOOL)
        for tag in READ_TAGS
    ),
    # Default-deny: anything not opted in above is excluded.
    RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
]


# A tool result is read by a model, and every field it carries is context the
# caller pays for. The route JSON is shaped for the app, so before it reaches
# the caller the result is trimmed of what a model never acts on:
#
#   * an absent value — a ``null``, an empty list, an empty object. Most of a
#     task row's fields are unset most of the time; leaving the key out says
#     the same thing.
#   * pictures — any ``*_base64`` data URI (a single avatar is often larger
#     than the rest of a task read combined) and any ``avatar_url``. Neither is
#     anything a caller can open or act on.
#   * a property's option list after the first row that carried it. A task list
#     repeats each property's whole definition — every option, label and colour
#     — on every row, which was nearly a quarter of a page of tasks. The first
#     row keeps it, so the caller still learns what the property accepts.
#
# Colours, icons and positions stay: the write tools set them, so a caller can
# be asked about them.
#
# A free-form field — a file's content, a dashboard's config, a property's
# value — passes through verbatim: what is inside it is the document's own,
# and a ``null`` there can mean something. Which fields are free-form is read
# off each tool's response schema when the server is built (see
# ``_free_form_keys``), so a new one is left alone by construction.
#
# Removing keys is possible because the tools publish no output schema (see
# ``_drop_output_schema``); against one, a missing key fails the client's
# validation.
_BASE64_SUFFIX = "_base64"
_UNREAD_KEYS = frozenset({"avatar_url"})


def _is_absent(value: Any) -> bool:
    return value is None or value == [] or value == {}


def _trim(
    value: Any,
    free_form: frozenset[str] = frozenset(),
    seen_properties: set[Any] | None = None,
) -> Any:
    """Return ``value`` without the fields a caller never acts on.

    Returns a new structure; the input is left untouched. ``free_form`` names
    the keys whose values pass through as they are; ``seen_properties`` carries
    the property ids whose options a row earlier in the same result has
    already shown.
    """
    if seen_properties is None:
        seen_properties = set()
    if isinstance(value, list):
        return [_trim(v, free_form, seen_properties) for v in value]
    if not isinstance(value, dict):
        return value

    trimmed: dict[str, Any] = {}
    property_id = value.get("property_id")
    repeats_options = "options" in value and property_id in seen_properties
    if "options" in value and property_id is not None:
        seen_properties.add(property_id)
    for key, v in value.items():
        if key in _UNREAD_KEYS or key.endswith(_BASE64_SUFFIX):
            continue
        if key == "options" and repeats_options:
            continue
        if key not in free_form:
            v = _trim(v, free_form, seen_properties)
        if not _is_absent(v):
            trimmed[key] = v
    return trimmed


class TrimResultMiddleware(Middleware):
    """Trim every tool result to what a caller acts on (see ``_trim``).

    Route-backed tools return the raw route JSON. Trimming here — after the
    route (and its RLS gates) have run — only removes fields from the payload;
    it never adds, changes or reorders anything.
    """

    def __init__(self, free_form_keys: dict[str, frozenset[str]] | None = None):
        self._free_form_keys = free_form_keys or {}

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        if result.structured_content is None:
            # Not a JSON body (route-backed tools only answer JSON or plain
            # text); there's nothing to trim.
            return result

        free_form = self._free_form_keys.get(context.message.name, frozenset())
        # The text block is serialized from the trimmed structure, so the two
        # always say the same thing.
        return ToolResult(
            structured_content=_trim(result.structured_content, free_form),
            meta=result.meta,
            is_error=result.is_error,
        )


async def _forward_authorization(request: httpx.Request) -> None:
    """Forward the caller's PAT to the in-process upstream route call.

    FastMCP strips ``authorization`` from forwarded headers by default; re-add it
    explicitly so the FastAPI route authenticates the caller and RLS scopes the
    request to *their* identity — never a shared or static token.
    """
    auth = get_http_headers(include={"authorization"}).get("authorization")
    if auth:
        request.headers["authorization"] = auth


# The list endpoints take ``conditions``/``sorting`` as a JSON *string* query
# param, which ``main._inject_query_schemas`` publishes as its decoded array
# type under ``content: application/json``. The MCP request builder reads that
# type but doesn't JSON-encode the value: handed an array argument it
# serializes each item with Python ``str()`` (single-quoted, e.g.
# ``{'field': 'due_date'}``), which the backend's ``json.loads`` rejects — every
# filtered/sorted list call 400s. Presenting the param to the model as a plain
# JSON string instead makes it send a string the builder forwards verbatim (valid
# JSON the backend parses). This touches only the MCP tool surface; the REST +
# Orval types keep the rich array schema.
_JSON_STRING_PARAMS = {
    "conditions": (
        "JSON-encoded array of filter conditions, AND-ed together. Each item: "
        '{"field": "<column>", "op": '
        '"eq"|"lt"|"lte"|"gt"|"gte"|"in_"|"ilike"|"is_null", "value": <val>}. '
        'An item with a "conditions" key is a group: '
        '{"logic": "and"|"or", "conditions": [...]}. '
        'Example: [{"field": "due_date", "op": "lt", "value": "2026-07-22"}]'
    ),
    "sorting": (
        "JSON-encoded array of sort fields. Each item: "
        '{"field": "<column>", "dir": "asc"|"desc"}. '
        'Example: [{"field": "due_date", "dir": "asc"}]'
    ),
}


def _stringify_json_query_params(route: object, component: object) -> None:
    """Retype array ``conditions``/``sorting`` tool params to JSON strings.

    A FastMCP ``mcp_component_fn`` (build-time): mutates each tool's input schema
    in place so the model passes a JSON string the request builder forwards as
    valid JSON, rather than an array it would mis-serialize. See the note on
    ``_JSON_STRING_PARAMS``.
    """
    params = getattr(component, "parameters", None)
    if not isinstance(params, dict):
        return
    props = params.get("properties")
    if not isinstance(props, dict):
        return
    for name, description in _JSON_STRING_PARAMS.items():
        schema = props.get(name)
        if isinstance(schema, dict) and schema.get("type") == "array":
            props[name] = {"type": "string", "description": description}


# A tool's input schema is what a model reads to call it, so it carries only
# what a caller supplies. Three things the OpenAPI document holds for other
# readers are taken out:
#
#   * cookie parameters. The browser's session cookie is declared on every
#     route's auth dependency, which made it an argument on every tool; an MCP
#     caller authenticates with its key in the ``Authorization`` header.
#   * ``title`` annotations. Pydantic titles every field after its own name
#     ("Task Id" on ``task_id``), which tells a model nothing the name doesn't.
#   * ``$defs`` nothing references any more — the filter and sort models that
#     ``_stringify_json_query_params`` replaced with a string.
_SUBSCHEMA_KEYS = ("items", "additionalProperties", "not")
_SUBSCHEMA_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")


def _strip_titles(schema: Any) -> None:
    """Remove ``title`` annotations from ``schema`` and its subschemas, in place.

    Walks schema positions only, so a *property* called ``title`` (a task's) is
    kept: ``properties`` maps names to schemas, and only the schemas are walked.
    """
    if not isinstance(schema, dict):
        return
    if isinstance(schema.get("title"), str):
        del schema["title"]
    for sub in (schema.get("properties") or {}).values():
        _strip_titles(sub)
    for sub in (schema.get("$defs") or {}).values():
        _strip_titles(sub)
    for key in _SUBSCHEMA_KEYS:
        _strip_titles(schema.get(key))
    for key in _SUBSCHEMA_LIST_KEYS:
        for sub in schema.get(key) or ():
            _strip_titles(sub)


_DEF_REF = re.compile(r'"#/\$defs/([^"]+)"')


def _prune_unused_defs(schema: dict[str, Any]) -> None:
    """Drop the ``$defs`` entries nothing outside them reaches, in place."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return
    body = {k: v for k, v in schema.items() if k != "$defs"}
    reached: set[str] = set()
    pending = set(_DEF_REF.findall(json.dumps(body)))
    while pending:
        name = pending.pop()
        if name in reached or name not in defs:
            continue
        reached.add(name)
        pending |= set(_DEF_REF.findall(json.dumps(defs[name])))
    kept = {k: v for k, v in defs.items() if k in reached}
    if kept:
        schema["$defs"] = kept
    else:
        del schema["$defs"]


def _clean_parameters(route: HTTPRoute, component: object) -> None:
    """Take out of a tool's input schema what a caller never supplies."""
    params = getattr(component, "parameters", None)
    if not isinstance(params, dict):
        return
    cookies = {p.name for p in route.parameters if p.location == "cookie"}
    props = params.get("properties")
    if isinstance(props, dict):
        for name in cookies:
            props.pop(name, None)
    if isinstance(params.get("required"), list):
        params["required"] = [n for n in params["required"] if n not in cookies]
    _strip_titles(params)
    _prune_unused_defs(params)


def _free_form_keys(schema: dict[str, Any] | None) -> frozenset[str]:
    """The property names whose value ``schema`` leaves free-form.

    A free-form value is one the schema gives no shape to — no type, or an
    object with no properties: a document's content, a dashboard's config, a
    property's value. ``_trim`` passes these through verbatim.
    """
    if not schema:
        return frozenset()
    defs = schema.get("$defs") or {}
    found: set[str] = set()
    visited: set[str] = set()

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            node = defs.get(name)
        return node

    def is_free_form(node: Any) -> bool:
        node = resolve(node)
        if not isinstance(node, dict):
            return False
        if "anyOf" in node:
            return any(
                is_free_form(n) for n in node["anyOf"] if n.get("type") != "null"
            )
        shaped = ("properties", "items", "enum", "const", "allOf", "oneOf", "$ref")
        if "type" not in node:
            return not any(k in node for k in shaped)
        return node["type"] == "object" and "properties" not in node

    def walk(node: Any) -> None:
        if isinstance(node, dict) and "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in visited:
                return
            visited.add(name)
        node = resolve(node)
        if not isinstance(node, dict):
            return
        for key, sub in (node.get("properties") or {}).items():
            if is_free_form(sub):
                found.add(key)
            walk(sub)
        for key in _SUBSCHEMA_KEYS:
            walk(node.get(key))
        for key in _SUBSCHEMA_LIST_KEYS:
            for sub in node.get(key) or ():
                walk(sub)

    walk(schema)
    return frozenset(found)


def _drop_output_schema(component: object) -> None:
    """Publish the tool without an output schema.

    A route's response schema is most of what ``tools/list`` sends — four
    fifths of it, in one measurement — and is there for a client to validate
    the structured result against, not for a model to read. Without it the
    result is still structured, and ``_trim`` may leave out keys the schema
    would have required.
    """
    if getattr(component, "output_schema", None) is not None:
        component.output_schema = None


def build_mcp_server(app: "FastAPI") -> FastMCP:
    """Build the route-backed, read-only MCP server from the FastAPI ``app``.

    The app must already have its routers included so the RouteMap can see them.
    """
    free_form_keys: dict[str, frozenset[str]] = {}

    def shape_tool(route: HTTPRoute, component: object) -> None:
        _stringify_json_query_params(route, component)
        _clean_parameters(route, component)
        name = getattr(component, "name", None)
        if name is not None:
            free_form_keys[name] = _free_form_keys(
                getattr(component, "output_schema", None)
            )
        _drop_output_schema(component)

    server = FastMCP.from_fastapi(
        app=app,
        name=PROJECT_NAME,
        route_maps=_ROUTE_MAPS,
        mcp_component_fn=shape_tool,
        httpx_client_kwargs={"event_hooks": {"request": [_forward_authorization]}},
    )
    server.add_middleware(TrimResultMiddleware(free_form_keys))
    return server
