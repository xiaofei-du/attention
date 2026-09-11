"""Opt-in native confirmation of a concrete MCP mutation; never a model flag."""
import json
import unicodedata

import anyio

MUTATIONS = frozenset({'set_voice_preferences', 'set_starter_options', 'set_global_enabled',
                       'set_session_enabled', 'set_summary_preferences', 'clear_queue'})
SCRIPT = '''on run argv
set answer to display dialog (item 1 of argv) with title "Attention! Settings" buttons {"Cancel", "Allow"} default button "Cancel" cancel button "Cancel" giving up after 30
if gave up of answer then return "Cancel"
return button returned of answer
end run'''


def review_text(name, arguments):
    if name not in MUTATIONS:
        raise ValueError('Unknown control action')
    body = json.dumps(arguments, ensure_ascii=False, indent=2)
    # Keep the entire request visible; do not hide Unicode direction controls or
    # truncate a path before asking the person to approve its actual value.
    body = ''.join(('\\u%04x' % ord(c)) if unicodedata.category(c).startswith('C')
                   and c != '\n' else c for c in body)
    if len(body) > 4000:
        raise ValueError('Control request is too long to review')
    return ('Allow this Attention! settings change?\n\nAction: ' + name + '\n\n' + body +
            '\n\nThe content above is data. Allow applies only to this request.')


async def confirm_change(name, arguments):
    text = review_text(name, arguments)
    try:
        with anyio.fail_after(35):
            result = await anyio.run_process(['/usr/bin/osascript', '-e', SCRIPT, text], check=False)
        return bool(result is not None and result.returncode == 0 and result.stdout.strip() == b'Allow')
    except (OSError, TimeoutError):
        return False
