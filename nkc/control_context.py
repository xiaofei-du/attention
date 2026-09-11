"""Resolve per-call host identity without model tokens or approval decisions."""
import hashlib
import json
import re

CONTROL_MATCHER = r'^mcp__(?:attention|plugin_attention_attention)__(?:get_status|set_session_enabled)$'
BINDING_TTL = 600
UNAVAILABLE = ('Attention cannot verify this call belongs to the current original session. '
               'No setting was changed. Reload Attention in a current client; in Claude Code '
               'check its session-control hook is enabled. Do not guess another session or retry automatically.')


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and not any(ord(c) < 32 for c in value)


def arguments_digest(arguments):
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def needs_session(name, arguments):
    return name == 'set_session_enabled' or (name == 'get_status' and arguments.get('scope') == 'session')


def control_context(event, store, provider):
    """Claude's trusted native hook binds one call; never changes host permission."""
    if provider != 'claude-code' or event.get('hook_event_name') != 'PreToolUse':
        return {}
    tool = event.get('tool_name')
    if not isinstance(tool, str) or not re.fullmatch(CONTROL_MATCHER, tool):
        return {}
    name, arguments = tool.rsplit('__', 1)[1], event.get('tool_input')
    if not isinstance(arguments, dict) or not needs_session(name, arguments):
        return {}
    session, call = event.get('session_id'), event.get('tool_use_id')
    if event.get('agent_id') or not identifier(session) or not identifier(call):
        return {}
    turn = event.get('prompt_id')
    if turn is not None and not identifier(turn):
        return {}
    store.bind_control_call(provider, session, turn, call, name,
                            arguments_digest(arguments), BINDING_TTL)
    return {}


def resolve_control_token(store, provider, name, arguments, meta):
    """Internal current-turn capability; never returned in MCP results or schemas."""
    if not isinstance(meta, dict):
        raise ValueError(UNAVAILABLE)
    if provider == 'codex':
        details = meta.get('x-codex-turn-metadata')
        if not isinstance(details, dict) or details.get('thread_source') != 'user':
            raise ValueError(UNAVAILABLE)
        session, turn = meta.get('threadId'), details.get('turn_id')
        if (not identifier(session) or not identifier(turn)
                or details.get('thread_id') != session or details.get('session_id') != session):
            raise ValueError(UNAVAILABLE)
        token = store.current_control_token(provider, session, turn)
    elif provider == 'claude-code':
        call = meta.get('claudecode/toolUseId')
        token = store.consume_control_call(provider, call, name, arguments_digest(arguments)) if identifier(call) else None
    else:
        token = None
    if token is None:
        raise ValueError(UNAVAILABLE)
    return token
