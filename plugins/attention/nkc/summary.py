"""Read short replies directly; extract a session-written summary for long replies."""

import json
import re
import unicodedata


MARKER = re.compile(r"(?:^|\n)<!-- nkc-summary:v1\s*\n(.*?)\n-->\s*\Z", re.DOTALL)
LEGACY_DIRECT_LIMIT = 160
MAX_SPEECH_UNITS = 300
MAX_TEXT_CHARACTERS = 1000
CJK = re.compile(r'[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff]')
SESSION_LABEL = 'Session: '


def speech_units(text):
    # A word takes roughly twice as long as a CJK character. This is a length
    # guard, not a promise about the synthesized audio's exact duration.
    characters = len(CJK.findall(text))
    rest = CJK.sub(' ', text)
    words = re.findall(r'\w+(?:[\u2019\x27]\w+)*', rest, flags=re.UNICODE)
    punctuation = len(re.sub(r'[\w\s\u2019\x27]', '', rest))
    return characters + 2 * len(words) + punctuation


def _plain_text(value):
    if not isinstance(value, str):
        raise ValueError("Summary fields must be text")
    text = " ".join(value.split())
    if any(token in text for token in ("[[", "]]", "<!--", "-->", "```", "http://", "https://")):
        raise ValueError("Summary must be plain spoken text")
    return text


def _direct_reply(reply, limit=MAX_SPEECH_UNITS):
    # Direct mode is for ordinary conversation. Technical output still needs
    # the original session's spoken summary, never a heuristic truncation.
    if reply.lstrip().startswith(('{', '[')) or any(token in reply for token in ('```', '~~~', '|', '<', '>', '://', 'www.')):
        raise ValueError('Reply contains content that needs a spoken summary')
    if (re.search(r'!?\[[^\]\n]+\](?:\(|\[)', reply) or
            re.search(r'(?<!\w)(?:/|~/|[A-Za-z]:\\)\S+', reply) or
            re.search(r':[a-z][\w-]*\{', reply)):
        raise ValueError('Reply contains a link, path, or display directive')
    # Formatting removal only: no paraphrasing or word selection.
    text = reply.strip()
    text = re.sub(r'^ {0,3}#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^ {0,3}[-*+][ \t]+', '', text, flags=re.MULTILINE)
    for pattern in (r'\*\*([^*\n]+)\*\*', r'__([^_\n]+)__',
                    r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'(?<!\w)_([^_\n]+)_(?!\w)',
                    r'`([^`\n]+)`'):
        text = re.sub(pattern, r'\1', text)
    text = _plain_text(text)
    if not text or len(text) > MAX_TEXT_CHARACTERS or speech_units(text) > limit:
        raise ValueError('Reply exceeds the spoken notification safety limit')
    return text


def summary_body(payload):
    if not isinstance(payload, dict) or set(payload) != {'why', 'done', 'next'}:
        raise ValueError('Notification requires why, done, next')
    parts = [_plain_text(payload[key]) for key in ('why', 'done', 'next')]
    if not parts[0] or not parts[1]:
        raise ValueError('Why and done cannot be empty')
    text = parts[0]
    for part in parts[1:]:
        if part:
            separator = '' if text[-1] in '。！？' or CJK.match(part[0]) else ' '
            text += separator + part
    if len(text) > MAX_TEXT_CHARACTERS or speech_units(text) > MAX_SPEECH_UNITS:
        raise ValueError('Summary is too long; do not read the full answer')
    return text


def extract_summary(message):
    if not isinstance(message, str):
        raise ValueError("No final message")
    match = MARKER.search(message)
    if not match:
        raise ValueError("No terminal notification summary")
    # A displayed code example is data, not this turn's notification.
    reply = message[:match.start()]
    fence = None
    for line in reply.splitlines():
        found = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if found:
            token = found.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
    if fence:
        raise ValueError("Summary is inside a code block")
    payload = json.loads(match.group(1))
    if payload == {'mode': 'direct'}:
        return _direct_reply(reply, limit=LEGACY_DIRECT_LIMIT)
    text = summary_body(payload)
    # Older/in-flight prompts may still emit why/done/next for a short reply.
    # Validate that metadata first, then avoid repeating the already-short answer.
    try:
        return _direct_reply(reply, limit=LEGACY_DIRECT_LIMIT)
    except ValueError:
        return text


def notification_body(message, staged=None, allow_direct=False):
    """New turns need no visible protocol. Still accept older in-flight turns."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError('No final message')
    # Staging is the session's decision to summarize. Do not discard its context
    # just because the visible answer happens to be short.
    if staged is not None:
        return staged
    if '<!-- nkc-summary:' in message:
        return extract_summary(message)
    if allow_direct:
        try:
            return _direct_reply(message)
        except ValueError:
            pass
    raise ValueError('Long or technical reply has no session-written summary')


def spoken_text(summary, name=""):
    name = _plain_text(name)
    if len(name) > 60:
        raise ValueError("Greeting name is too long")
    greeting = "Hello, " + name + "。" if name else "Hello。"
    return greeting + _plain_text(summary)


def validate_start(text):
    """An opening is persistent literal speech text, never code or instructions."""
    if not isinstance(text, str) or len(text) > 120 or any(ord(char) < 32 for char in text):
        raise ValueError('Start must be a single line of at most 120 characters')
    if text:
        _direct_reply(text)  # Validate plain speech; preserve the supplied spelling.
    return text


def opening_prefix(start, body):
    start = validate_start(start)
    separator = '' if (not start or not body or start[-1].isspace()
                       or start[-1] in '。！？；：，、') else ' '
    return start + separator


def speech_text(summary, start):
    body = _plain_text(summary)
    return opening_prefix(start, body) + body


def spoken_session_name(value):
    # Metadata is literal speech, never say markup or a prompt. Long first-message
    # previews are not useful spoken names; omit them rather than truncating them.
    if (not isinstance(value, str) or len(value) > 200 or
            any(unicodedata.category(char).startswith('C') for char in value) or
            '<' in value or '>' in value):
        return ''
    try:
        return _plain_text(value)
    except ValueError:
        return ''


def notification_text(summary, settings, session_name=''):
    if settings.get('announce_session_name'):
        name = spoken_session_name(session_name)
        if name:
            summary = SESSION_LABEL + name + '. ' + summary
    # An audio opening replaces the spoken greeting; the stored text can be reused later.
    return speech_text(summary, '' if settings.get('start_audio') else settings['start'])
