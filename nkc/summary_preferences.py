"""Finite summary preferences; only application-owned guidance enters hooks."""

TONES = {
    'conversational': 'Use natural conversational language with I and you.',
    'calm': 'Use a calm, measured conversational tone without adding reassurance you cannot support.',
    'upbeat': 'Use a warm, upbeat conversational tone without exaggerating progress or results.',
}
FOCUSES = {
    'balanced': 'Balance recognizable context, actual progress and the real next action or decision.',
    'context': 'Give extra attention to the task context and goal so the user can recognize this session.',
    'progress': 'Give extra attention to what changed this round and what was actually verified.',
    'next_steps': 'Give extra attention to the next action or decision, including what the user needs to decide.',
}
DEFAULTS = {'enabled': True, 'target_seconds': 30, 'tone': 'conversational', 'focus': 'balanced'}


def valid_value(key, value):
    if key == 'enabled':
        return type(value) is bool
    if key == 'target_seconds':
        return type(value) is int and 10 <= value <= 90
    choices = TONES if key == 'tone' else FOCUSES
    return type(value) is str and value in choices


def normalize(preferences):
    # Defense in depth for migrated/corrupt SQLite data, not a sandbox against
    # an agent able to change this program or its database directly.
    return {key: preferences.get(key) if valid_value(key, preferences.get(key)) else default
            for key, default in DEFAULTS.items()}


def validate_patch(preferences):
    if not preferences or not set(preferences) <= set(DEFAULTS):
        raise ValueError('Provide enabled, target_seconds, tone and/or focus; free-form summary instructions are not supported')
    for key, value in preferences.items():
        if not valid_value(key, value):
            choices = ('a boolean' if key == 'enabled' else 'an integer from 10 to 90'
                       if key == 'target_seconds' else ', '.join(TONES if key == 'tone' else FOCUSES))
            raise ValueError('Summary ' + key + ' must be ' + choices)
    return preferences


def prompt_guidance(preferences):
    saved = normalize(preferences)
    return (f"Target seconds: {saved['target_seconds']} (soft guide, never a minimum). "
            f"Tone: {saved['tone']}. {TONES[saved['tone']]} "
            f"Focus: {saved['focus']}. {FOCUSES[saved['focus']]} "
            'Every summary still covers context, actual progress and next steps when relevant; never invent or pad.')


def migrate(db):
    columns = {row['name'] for row in db.execute('PRAGMA table_info(summary_preferences)')}
    if 'enabled' not in columns:
        db.execute('ALTER TABLE summary_preferences ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))')
    for field, choices in [('tone', TONES), ('focus', FOCUSES)]:
        if field not in columns:
            allowed = ','.join("'" + key + "'" for key in choices)
            db.execute(f"ALTER TABLE summary_preferences ADD COLUMN {field} TEXT NOT NULL "
                       f"DEFAULT '{DEFAULTS[field]}' CHECK({field} IN ({allowed}))")
    # Keep an empty compatibility column so an already-running old MCP status
    # query still works. Old writers cannot restore the retired free-text path.
    db.execute("UPDATE summary_preferences SET custom_instructions='' WHERE custom_instructions IS NOT ''")
    for action in ('INSERT', 'UPDATE OF custom_instructions'):
        suffix = 'insert' if action == 'INSERT' else 'update'
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS reject_freeform_summary_{suffix}
            BEFORE {action} ON summary_preferences WHEN NEW.custom_instructions IS NOT ''
            BEGIN SELECT RAISE(ABORT, 'Free-form summary instructions retired; reload client and use tone/focus'); END""")
    # Older processes can finish after the switch changes. Enforce the content
    # boundary in SQLite too, without relying on their cached mode or prompt.
    for action in ('INSERT', 'UPDATE OF body'):
        suffix = 'insert' if action == 'INSERT' else 'update'
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS reject_disabled_summary_{suffix}
            BEFORE {action} ON turn_summaries WHEN NEW.body IS NOT NULL
                AND (SELECT enabled FROM summary_preferences WHERE id=1)=0
            BEGIN SELECT RAISE(ABORT, 'Summary generation is disabled'); END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS strip_disabled_job_body_{suffix}
            AFTER {action} ON jobs WHEN NEW.body<>''
                AND (SELECT enabled FROM summary_preferences WHERE id=1)=0
            BEGIN UPDATE jobs SET body='' WHERE id=NEW.id; END""")
