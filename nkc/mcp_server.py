"""Nine local notification tools, served over stdio by the official MCP SDK."""

import anyio
import os
from contextlib import nullcontext
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, ToolAnnotations

from .store import Store
from .summary_preferences import TONES, FOCUSES
from .platform_support import platform_status
from .control_context import needs_session, resolve_control_token


def object_schema(properties=None, required=None, patch=False):
    schema = {'type': 'object', 'properties': properties or {}, 'additionalProperties': False}
    if required:
        schema['required'] = required
    if patch:
        schema['minProperties'] = 1
    return schema


VOICE = {'type': 'string', 'minLength': 1, 'maxLength': 100}
BOOL = {'type': 'boolean'}
OPENING = {'oneOf': [
    object_schema({'type': {'const': 'none'}}, ['type']),
    object_schema({'type': {'const': 'text'}, 'text': {'type': 'string', 'maxLength': 120}}, ['type', 'text']),
    object_schema({'type': {'const': 'system'}, 'name': {'type': 'string', 'minLength': 1}}, ['type', 'name']),
    object_schema({'type': {'const': 'custom'}, 'path': {'type': 'string', 'minLength': 1}}, ['type', 'path']),
]}


def tool(name, description, schema, read_only=False, destructive=False, idempotent=True):
    return Tool(name=name, description=description, inputSchema=schema,
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive,
                                            idempotentHint=idempotent, openWorldHint=False))


TOOLS = [
    tool('get_status', 'Read shared speech settings and compact queue status. Use scope=session to include this '
         'original session’s preference and effective state, resolved from native host context. Default scope=shared. '
         'Does not read summary bodies or play. Missing session context returns a setup error; never guess identity.',
         object_schema({'scope': {'enum': ['shared', 'session'], 'default': 'shared'}}), read_only=True),
    tool('list_voices', 'Refresh and list all locally installed speech voices with Apple language/gender metadata. '
         'Discovery only: no selection, playback, downloads or API calls.', object_schema(), read_only=True),
    tool('set_voice_preferences', 'On an explicit user request, update only supplied shared voice settings. '
         'Applies at next playback; never auditions. Missing voices return download guidance, preserving the preference. '
         'duck_media defaults false on new installs. Enabling may request system-audio permission; no microphone. '
         'If unavailable, ordinary playback continues. gender=default uses saved voices; auto follows sentence language, fixed uses the configured voice language.',
         object_schema({'gender': {'enum': ['default', 'male', 'female']}, 'voice': VOICE, 'english_voice': VOICE,
                        'voice_mode': {'enum': ['auto', 'fixed']}, 'duck_media': BOOL, 'rate': {'type': 'integer', 'minimum': 80, 'maximum': 500}},
                       patch=True)),
    tool('get_starter_sound_options', 'List this Mac’s actual system alert sound names and supported custom audio formats. '
         'Does not select or preview audio. For speech voices use list_voices.', object_schema(), read_only=True),
    tool('set_starter_options', 'On an explicit user request, atomically update shared opening and/or session-name reporting. '
         'Omitted fields stay unchanged. Opening is literal text, a listed system sound, a provided custom local audio path, '
         'or none (empty). Audio replaces the text opening. Custom files are validated and copied locally; no upload UI. '
         'announce_session_name adds the existing session-name clause after the opening. Does not play or rename sessions.',
         object_schema({'opening': OPENING, 'announce_session_name': BOOL}, patch=True)),
    tool('set_global_enabled', 'Only for an explicit request to turn ALL speech off/on. Off immediately cancels current '
         'and queued speech, clears staged summaries and discards completions while off. On preserves session choices, '
         'without replay. An unqualified mute request belongs to set_session_enabled.',
         object_schema({'enabled': BOOL}, ['enabled']), destructive=True),
    tool('set_session_enabled', 'Only for an explicit request to mute/unmute THIS original session. Its identity is '
         'resolved from native host context; supply only enabled. Off cancels its current/queued speech. New sessions '
         'default on. On permits future speech without replay and cannot override global off. Missing or stale context '
         'returns a setup error without changing settings. Never guess identity or retry a cancelled confirmation.',
         object_schema({'enabled': BOOL}, ['enabled']), destructive=True),
    tool('set_summary_preferences', 'On explicit request, update shared finite summary preferences. '
         'enabled defaults true; false plays only the saved starter and optional session name, never the reply or summary. '
         'Off clears pending notifications and staged content, and cancels current content speech. '
         'Re-enabling preserves other preferences without restoring old content. Neither setting unmutes speech. '
         'target_seconds is a soft guide (10-90, default 30); tone is conversational (default), calm or upbeat; '
         'focus is balanced (default), context, progress or next_steps. Focus adds emphasis without omitting '
         'context, actual progress or a relevant next decision. No free-form instructions. The original agent '
         'chooses direct reply versus summary only while enabled; no extra LLM or playback. When false, stop following '
         'earlier summary instructions now. Re-enable needs no token; fresh generation instructions arrive next prompt. '
         'Do not reuse old summary commands. Ordinary disabled rounds inject no prompt; old sessions get one revocation.',
         object_schema({'enabled': BOOL, 'target_seconds': {'type': 'integer', 'minimum': 10, 'maximum': 90},
                        'tone': {'enum': list(TONES)}, 'focus': {'enum': list(FOCUSES)}}, patch=True), destructive=True),
    tool('clear_queue', 'On an explicit user request, cancel all currently pending notifications across Codex and Claude Code. '
         'Current speech continues. Settings, unqueued summaries and dedupe receipts remain. Future notifications enqueue '
         'normally. Returns the actual cleared count; calling again later can clear newly arrived notifications.',
         object_schema(), destructive=True, idempotent=False),
]


def create_server(store, availability=None, confirm_controls=False, approver=None, provider='codex'):
    if provider not in ('codex', 'claude-code'):
        raise ValueError('Unsupported MCP provider')
    server = Server(os.environ.get('ATTENTION_SERVER_NAME', 'no-keyboard-code'), version='0.1.0', instructions=(
        'Control the local shared spoken notifier only on explicit user requests. Read tools do not play. '
        'Do not change settings for examples or feature discussions. Session identity comes from native call context. '
        'No MCP summary submission or opening preview; original-session hooks and CLI still handle summaries.'))
    if availability is None or availability['supported']:
        from .controls import Controls
        controls = Controls(store)
    else:
        controls = None
    names = {entry.name for entry in TOOLS}
    from .confirmation import MUTATIONS, confirm_change
    approve = approver or confirm_change
    confirmation_lock = anyio.Lock()

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name, arguments):
        if name not in names:
            raise ValueError('Unknown notification control tool: ' + name)
        if controls is None:
            return availability
        bound_arguments = dict(arguments)
        if needs_session(name, arguments):
            try:
                meta = server.request_context.meta
            except LookupError:
                meta = None
            metadata = meta.model_dump(by_alias=True) if meta is not None else None
            token = await anyio.to_thread.run_sync(
                lambda: resolve_control_token(store, provider, name, arguments, metadata))
            bound_arguments['token'] = token
        if name == 'get_status':
            bound_arguments.pop('scope', None)
        if confirm_controls and name in MUTATIONS:
            async with confirmation_lock:
                if not await approve(name, arguments):
                    raise PermissionError('Control change was not confirmed; settings unchanged')
                return await anyio.to_thread.run_sync(lambda: getattr(controls, name)(**bound_arguments))
        # SDK validates the strict input schema before this handler. Blocking
        # SQLite / Apple inventory work runs off the protocol event loop.
        return await anyio.to_thread.run_sync(lambda: getattr(controls, name)(**bound_arguments))

    return server


async def serve(state_dir, availability=None, confirm_controls=False, summary_socket=None, provider='codex'):
    availability = platform_status() if availability is None else availability
    store = Store(state_dir) if availability['supported'] else None
    server = create_server(store, availability, confirm_controls=confirm_controls, provider=provider)
    broker = nullcontext()
    if summary_socket and store:
        from .submission import SharedSummaryBroker
        broker = SharedSummaryBroker(store, summary_socket)
    with broker:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
