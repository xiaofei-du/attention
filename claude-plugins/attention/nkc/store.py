"""Durable, shared local queue. Audio ownership is enforced by runtime's lock."""

import sqlite3
import json
import time
import uuid
import hashlib
from contextlib import contextmanager
from pathlib import Path

from . import summary_preferences as summary_options


BODY_RETENTION_SECONDS = 24 * 3600
CONTROL_TOMBSTONE = ("UPDATE control_bindings SET consumed=1,session_id='',turn_id='',"
                     "tool_name='',arguments_digest='',expires=0 ")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    name TEXT NOT NULL, voice TEXT NOT NULL, rate INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    provider TEXT, session_id TEXT, turn_id TEXT,
                    PRIMARY KEY(provider, session_id));
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    received REAL NOT NULL, ready_after REAL NOT NULL,
                    error TEXT, UNIQUE(provider, session_id, turn_id));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created REAL, session_id TEXT,
                    kind TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS turn_summaries (
                    provider TEXT, session_id TEXT, turn_id TEXT,
                    token TEXT UNIQUE NOT NULL, body TEXT,
                    PRIMARY KEY(provider, session_id, turn_id));
                CREATE TABLE IF NOT EXISTS session_preferences (
                    provider TEXT NOT NULL, session_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    PRIMARY KEY(provider, session_id));
                CREATE TABLE IF NOT EXISTS session_sources (
                    provider TEXT NOT NULL, session_id TEXT NOT NULL,
                    config_home TEXT NOT NULL DEFAULT '', transcript_path TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(provider, session_id));
                CREATE TABLE IF NOT EXISTS summary_preferences (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    target_seconds INTEGER NOT NULL DEFAULT 30,
                    custom_instructions TEXT NOT NULL DEFAULT '');
                INSERT OR IGNORE INTO summary_preferences(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS onboarding (
                    id INTEGER PRIMARY KEY CHECK(id=1));
                CREATE TABLE IF NOT EXISTS control_bindings (
                    provider TEXT NOT NULL, call_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL, arguments_digest TEXT NOT NULL,
                    expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(provider,call_id));
            """)
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='summary_context'").fetchone():
                db.execute('CREATE TABLE summary_context (provider TEXT, session_id TEXT, '
                           'enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), PRIMARY KEY(provider,session_id))')
                # Old runtimes injected instructions on every registered turn.
                # Invalidate those once on their next disabled prompt, even when
                # an upgrade happens while the shared summary switch is off.
                db.execute('INSERT INTO summary_context SELECT provider,session_id,1 FROM turns')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(settings)')}
            new_settings = db.execute('SELECT 1 FROM settings WHERE id=1').fetchone() is None
            if 'paused' in columns:
                db.execute("INSERT OR IGNORE INTO settings(id,paused,name,voice,rate) "
                           "VALUES(1,1,'sunshine','Meijia',180)")
            else:
                db.execute("INSERT OR IGNORE INTO settings(id,name,voice,rate) "
                           "VALUES(1,'sunshine','Meijia',180)")
            if 'duck_media' not in columns:
                db.execute('ALTER TABLE settings ADD COLUMN duck_media INTEGER NOT NULL DEFAULT 0 CHECK(duck_media IN (0,1))')
                if not new_settings:
                    db.execute('UPDATE settings SET duck_media=1 WHERE id=1')
            if 'voice_mode' not in columns:
                db.execute("ALTER TABLE settings ADD COLUMN voice_mode TEXT NOT NULL DEFAULT 'auto'")
            if 'english_voice' not in columns:
                db.execute("ALTER TABLE settings ADD COLUMN english_voice TEXT NOT NULL DEFAULT 'Samantha'")
            if 'voice_gender' not in columns:
                db.execute("ALTER TABLE settings ADD COLUMN voice_gender TEXT NOT NULL DEFAULT 'default' "
                           "CHECK(voice_gender IN ('default','male','female'))")
            if 'start' not in columns:
                from .summary import spoken_text
                name = db.execute('SELECT name FROM settings WHERE id=1').fetchone()['name']
                db.execute("ALTER TABLE settings ADD COLUMN start TEXT NOT NULL DEFAULT ''")
                db.execute('UPDATE settings SET start=? WHERE id=1', (spoken_text('', name),))
            if new_settings:
                # Seed only fresh installs; preserve every existing text/audio/empty opening.
                db.execute('UPDATE settings SET start=? WHERE id=1', ('hey sunshine',))
            if 'start_audio' not in columns:
                db.execute("ALTER TABLE settings ADD COLUMN start_audio TEXT NOT NULL DEFAULT ''")
            if 'announce_session_name' not in columns:
                db.execute('ALTER TABLE settings ADD COLUMN announce_session_name INTEGER NOT NULL DEFAULT 0')
            if 'global_voice_enabled' not in columns:
                db.execute('ALTER TABLE settings ADD COLUMN global_voice_enabled INTEGER NOT NULL DEFAULT 1 '
                           'CHECK(global_voice_enabled IN (0,1))')
            if 'paused' in columns:
                if db.execute('SELECT paused FROM settings WHERE id=1').fetchone()['paused']:
                    # Preserve the user's silence without keeping a hidden gate
                    # or suddenly playing a legacy paused backlog after upgrade.
                    db.execute('UPDATE settings SET global_voice_enabled=0 WHERE id=1')
                    db.execute("UPDATE jobs SET status='cancelled',error='Legacy pause converted to global off' "
                               "WHERE status IN ('pending','speaking')")
                    db.execute('UPDATE turn_summaries SET body=NULL')
                db.execute('ALTER TABLE settings DROP COLUMN paused')
            summary_options.migrate(db)
            self._configure_privacy(db)
            self._expire_summaries(db)
            db.execute(CONTROL_TOMBSTONE + 'WHERE consumed=0 AND expires<?', (time.time(),))
            if db.execute('PRAGMA user_version').fetchone()[0] < 2:
                # secure_delete covers current updates; VACUUM removes free pages
                # left by pre-migration deletions. Never make a plaintext backup.
                db.commit()
                db.execute('VACUUM')
                db.execute('PRAGMA user_version=2')

    @staticmethod
    def _configure_privacy(db):
        columns = {row['name'] for row in db.execute('PRAGMA table_info(turn_summaries)')}
        if 'updated' not in columns:
            db.execute('ALTER TABLE turn_summaries ADD COLUMN updated REAL NOT NULL DEFAULT 0')
        # Database triggers also cover still-running clients using older Store code.
        for action in ('INSERT', 'UPDATE OF status,body'):
            suffix = 'insert' if action == 'INSERT' else 'update'
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS erase_terminal_body_{suffix}
                AFTER {action} ON jobs WHEN NEW.status NOT IN ('pending','speaking') AND NEW.body<>''
                BEGIN UPDATE jobs SET body='' WHERE id=NEW.id; END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS consume_staged_summary
            AFTER INSERT ON jobs BEGIN
            UPDATE turn_summaries SET body=NULL WHERE provider=NEW.provider
                AND session_id=NEW.session_id AND turn_id=NEW.turn_id;
            END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS erase_repeated_summary
            AFTER UPDATE OF body ON turn_summaries WHEN NEW.body IS NOT NULL AND EXISTS
                (SELECT 1 FROM jobs WHERE provider=NEW.provider AND session_id=NEW.session_id AND turn_id=NEW.turn_id)
            BEGIN UPDATE turn_summaries SET body=NULL WHERE token=NEW.token; END""")
        db.execute("UPDATE jobs SET body='' WHERE status NOT IN ('pending','speaking') AND body<>''")
        db.execute("""UPDATE turn_summaries SET body=NULL WHERE body IS NOT NULL AND EXISTS
            (SELECT 1 FROM jobs WHERE jobs.provider=turn_summaries.provider
             AND jobs.session_id=turn_summaries.session_id AND jobs.turn_id=turn_summaries.turn_id)""")

    @staticmethod
    def _expire_summaries(db):
        cutoff = time.time() - BODY_RETENTION_SECONDS
        db.execute("UPDATE jobs SET status='cancelled',error='Notification expired' "
                   "WHERE status='pending' AND received<?", (cutoff,))
        db.execute('UPDATE turn_summaries SET body=NULL WHERE body IS NOT NULL AND updated<?', (cutoff,))

    @contextmanager
    def db(self, timeout=15):
        db = sqlite3.connect(str(self.root / 'queue.sqlite3'), timeout=timeout)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.db() as db:
            settings = dict(db.execute('SELECT * FROM settings WHERE id=1').fetchone())
            settings['start_audio'] = json.loads(settings['start_audio']) if settings['start_audio'] else None
            settings['duck_media'] = bool(settings['duck_media'])
            settings['announce_session_name'] = bool(settings['announce_session_name'])
            settings['global_voice_enabled'] = bool(settings['global_voice_enabled'])
            return settings

    def claim_onboarding(self):
        """Offer once across processes/providers; this is not a display receipt."""
        with self.db() as db:
            return db.execute('INSERT OR IGNORE INTO onboarding(id) VALUES(1)').rowcount == 1

    def claim_summary_context(self, provider, session_id):
        """Track emitted instructions, not chat history. Return preferences + revocation."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            preferences = self._summary_preferences(db)
            previous = db.execute('SELECT enabled FROM summary_context WHERE provider=? AND session_id=?',
                                  (provider, session_id)).fetchone()
            revoke = bool(previous and previous['enabled'] and not preferences['enabled'])
            db.execute('INSERT OR REPLACE INTO summary_context VALUES(?,?,?)',
                       (provider, session_id, int(preferences['enabled'])))
            return preferences, revoke

    def current_control_token(self, provider, session_id, turn_id=None):
        """Only native adapters supply identity; never guess the latest session."""
        with self.db() as db:
            row = db.execute('SELECT s.token,s.turn_id FROM turn_summaries s JOIN turns '
                             'USING(provider,session_id,turn_id) WHERE s.provider=? AND s.session_id=?',
                             (provider, session_id)).fetchone()
            if row is None or (turn_id is not None and row['turn_id'] != turn_id):
                return None
            return row['token']

    def bind_control_call(self, provider, session_id, turn_id, call_id, name, digest, ttl):
        """First delivery wins. Repeated/conflicting hook deliveries never rearm a call."""
        call_id = hashlib.sha256(call_id.encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(CONTROL_TOMBSTONE + 'WHERE consumed=0 AND expires<?', (time.time(),))
            current = db.execute('SELECT turn_id FROM turns WHERE provider=? AND session_id=?',
                                 (provider, session_id)).fetchone()
            if current is None or (turn_id is not None and current['turn_id'] != turn_id):
                return
            turn_id = current['turn_id']
            values = (session_id, turn_id, name, digest)
            previous = db.execute('SELECT * FROM control_bindings WHERE provider=? AND call_id=?',
                                  (provider, call_id)).fetchone()
            if previous:
                if tuple(previous[k] for k in ('session_id', 'turn_id', 'tool_name', 'arguments_digest')) != values:
                    db.execute(CONTROL_TOMBSTONE + 'WHERE provider=? AND call_id=?',
                               (provider, call_id))
                return
            db.execute('INSERT INTO control_bindings VALUES(?,?,?,?,?,?,?,0)',
                       (provider, call_id, *values, time.time() + ttl))

    def consume_control_call(self, provider, call_id, name, digest):
        call_id = hashlib.sha256(call_id.encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM control_bindings WHERE provider=? AND call_id=?',
                             (provider, call_id)).fetchone()
            if row is None or row['consumed']:
                return None
            # Retain only an opaque receipt: delayed duplicate hooks cannot
            # recreate an expired call against a newer turn after cleanup.
            db.execute(CONTROL_TOMBSTONE + 'WHERE provider=? AND call_id=?',
                       (provider, call_id))
            if row['expires'] < time.time() or row['tool_name'] != name or row['arguments_digest'] != digest:
                return None
            current = db.execute('SELECT s.token FROM turn_summaries s JOIN turns '
                                 'USING(provider,session_id,turn_id) '
                                 'WHERE s.provider=? AND s.session_id=? AND s.turn_id=?',
                                 (provider, row['session_id'], row['turn_id'])).fetchone()
            return current['token'] if current else None

    @staticmethod
    def _global_enabled(db):
        return bool(db.execute('SELECT global_voice_enabled FROM settings WHERE id=1').fetchone()[0])

    def global_enabled(self):
        with self.db() as db:
            return self._global_enabled(db)

    def clear_queue(self):
        """Cancel pending receipts at one transaction boundary; never stop speech."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            return db.execute("UPDATE jobs SET status='cancelled',error='Queue cleared' "
                              "WHERE status='pending'").rowcount

    def queue_status(self):
        with self.db() as db:
            db.execute('BEGIN')
            counts = {row['status']: row['count'] for row in db.execute(
                'SELECT status,COUNT(*) AS count FROM jobs GROUP BY status')}
            speaking = [dict(row) for row in db.execute(
                "SELECT provider,session_id FROM jobs WHERE status='speaking' ORDER BY id")]
            return {'pending': counts.get('pending', 0), 'speaking': speaking, 'counts': counts}

    def summary_preferences(self):
        with self.db() as db:
            return self._summary_preferences(db)

    @staticmethod
    def _summary_preferences(db):
        row = dict(db.execute('SELECT enabled,target_seconds,tone,focus FROM summary_preferences WHERE id=1').fetchone())
        row['enabled'] = bool(row['enabled'])
        return summary_options.normalize(row)

    def set_summary_preferences(self, **preferences):
        patch = summary_options.validate_patch(preferences)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE summary_preferences SET ' + ','.join(key + '=?' for key in patch) + ' WHERE id=1',
                       tuple(patch.values()))
            if patch.get('enabled') is False:
                db.execute('UPDATE turn_summaries SET body=NULL')
                db.execute("UPDATE jobs SET status='cancelled',error='Summary content disabled' "
                           "WHERE status='speaking' AND body<>''")
                db.execute("UPDATE jobs SET status='cancelled',error='Summary mode changed; queue cleared' "
                           "WHERE status='pending'")
        return self.summary_preferences()

    @staticmethod
    def _summary_enabled(db):
        return bool(db.execute('SELECT enabled FROM summary_preferences WHERE id=1').fetchone()[0])

    def _patch_settings(self, patch):
        allowed = {'name', 'voice', 'rate', 'voice_mode', 'english_voice', 'voice_gender',
                   'start', 'start_audio', 'announce_session_name', 'duck_media'}
        if not patch or not set(patch) <= allowed:
            raise ValueError('Invalid settings update')
        # Only validated, explicitly supplied columns are updated. A parallel
        # session's unrelated changes cannot be overwritten by a stale snapshot.
        with self.db() as db:
            db.execute('UPDATE settings SET ' + ','.join(key + '=?' for key in patch) + ' WHERE id=1',
                       tuple(patch.values()))

    @staticmethod
    def _voice_patch(voice=None, rate=None, voice_mode=None, english_voice=None, gender=None, duck_media=None):
        patch = {}
        for key, value in (('voice', voice), ('english_voice', english_voice)):
            if value is not None:
                if (not isinstance(value, str) or not value.strip() or len(value) > 100
                        or any(ord(c) < 32 for c in value)):
                    raise ValueError('Invalid voice name')
                patch[key] = value
        if voice_mode is not None:
            if voice_mode not in ('auto', 'fixed'):
                raise ValueError('Voice mode must be auto or fixed')
            patch['voice_mode'] = voice_mode
        if rate is not None:
            if type(rate) is not int or not 80 <= rate <= 500:
                raise ValueError('Speech rate must be an integer between 80 and 500')
            patch['rate'] = rate
        if gender is not None:
            if gender not in ('default', 'male', 'female'):
                raise ValueError('Voice gender must be default, male or female')
            patch['voice_gender'] = gender
        if duck_media is not None:
            if type(duck_media) is not bool:
                raise ValueError('Media ducking must be a boolean')
            patch['duck_media'] = int(duck_media)
        return patch

    def set_voice_preferences(self, voice=None, rate=None, voice_mode=None, english_voice=None, gender=None, duck_media=None):
        self._patch_settings(self._voice_patch(voice, rate, voice_mode, english_voice, gender, duck_media))

    def set_starter_options(self, opening=None, announce_session_name=None):
        from .summary import validate_start
        from .opening import prepare_audio
        patch = {}
        if announce_session_name is not None:
            if type(announce_session_name) is not bool:
                raise ValueError('Session name report enabled must be a boolean')
            patch['announce_session_name'] = int(announce_session_name)
        if opening is not None:
            if not isinstance(opening, dict):
                raise ValueError('Opening must be an object')
            kind = opening.get('type')
            if kind == 'none' and set(opening) == {'type'}:
                patch.update(start='', start_audio='')
            elif kind == 'text' and set(opening) == {'type', 'text'}:
                patch.update(start=validate_start(opening['text']), start_audio='')
            elif kind in ('system', 'custom'):
                prepared = prepare_audio(opening, self.root / 'opening-audio')
                patch['start_audio'] = json.dumps(prepared, ensure_ascii=False)
            else:
                raise ValueError('Opening requires type none, text with text, system with name, or custom with path')
        self._patch_settings(patch)

    def session_for_token(self, token):
        with self.db() as db:
            row = db.execute('SELECT s.provider,s.session_id FROM turn_summaries AS s JOIN turns '
                             'USING(provider,session_id,turn_id) WHERE s.token=?', (token,)).fetchone()
            if row is None:
                raise ValueError('Unknown or expired notification token')
            return dict(row, enabled=self._session_enabled(db, row['provider'], row['session_id']))

    def set_global_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Global speech enabled must be a boolean')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE settings SET global_voice_enabled=? WHERE id=1', (int(enabled),))
            if not enabled:
                db.execute("UPDATE jobs SET status='cancelled',error='Global speech disabled' "
                           "WHERE status IN ('pending','speaking')")
                db.execute('UPDATE turn_summaries SET body=NULL')

    @staticmethod
    def _suppress_notification(db, provider, session_id, turn_id, reason='Global speech disabled'):
        # An empty cancellation receipt prevents a delayed duplicate Stop from
        # replaying a round completed while muted. No notification body is saved.
        db.execute("INSERT OR IGNORE INTO jobs(provider,session_id,turn_id,body,status,received,ready_after,error) "
                   "VALUES(?,?,?,'','cancelled',?,0,?)",
                   (provider, session_id, turn_id, time.time(), reason))
        db.execute("UPDATE jobs SET status='cancelled',error=? "
                   "WHERE provider=? AND session_id=? AND turn_id=? AND status IN ('pending','speaking')",
                   (reason, provider, session_id, turn_id))
        db.execute('UPDATE turn_summaries SET body=NULL WHERE provider=? AND session_id=? AND turn_id=?',
                   (provider, session_id, turn_id))

    def suppress_notification(self, provider, session_id, turn_id, *, reason='Global speech disabled'):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._suppress_notification(db, provider, session_id, turn_id, reason)

    def set_announce_session_name(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Session name report enabled must be a boolean')
        with self.db() as db:
            db.execute('UPDATE settings SET announce_session_name=? WHERE id=1', (int(enabled),))

    def set_voice_gender(self, gender):
        if not isinstance(gender, str) or gender not in ('default', 'male', 'female'):
            raise ValueError('Voice gender must be default, male or female')
        with self.db() as db:
            db.execute('UPDATE settings SET voice_gender=? WHERE id=1', (gender,))

    def record_session_source(self, provider, session_id, config_home='', transcript_path=''):
        with self.db() as db:
            db.execute('INSERT INTO session_sources VALUES(?,?,?,?) ON CONFLICT(provider,session_id) '
                       'DO UPDATE SET config_home=COALESCE(NULLIF(excluded.config_home,\'\'),config_home), '
                       'transcript_path=COALESCE(NULLIF(excluded.transcript_path,\'\'),transcript_path)',
                       (provider, session_id, config_home, transcript_path))

    def session_source(self, provider, session_id):
        with self.db() as db:
            row = db.execute('SELECT config_home,transcript_path FROM session_sources '
                             'WHERE provider=? AND session_id=?', (provider, session_id)).fetchone()
            return dict(row) if row else {}

    def configure(self, name=None, voice=None, rate=None, voice_mode=None, english_voice=None, duck_media=None):
        from .summary import spoken_text
        patch = self._voice_patch(voice, rate, voice_mode, english_voice, duck_media=duck_media)
        if name is not None:
            patch.update(name=name, start=spoken_text('', name), start_audio='')
        if patch:
            self._patch_settings(patch)

    def set_start(self, text):
        from .summary import validate_start
        text = validate_start(text)
        with self.db() as db:
            db.execute("UPDATE settings SET start=?,start_audio='' WHERE id=1", (text,))

    def set_start_audio(self, payload):
        from .opening import prepare_audio
        prepared = prepare_audio(payload, self.root / 'opening-audio')
        with self.db() as db:
            db.execute('UPDATE settings SET start_audio=? WHERE id=1', (json.dumps(prepared, ensure_ascii=False),))
        return prepared

    @staticmethod
    def _session_enabled(db, provider, session_id):
        row = db.execute('SELECT enabled FROM session_preferences WHERE provider=? AND session_id=?',
                         (provider, session_id)).fetchone()
        return bool(row['enabled']) if row else True

    def session_enabled(self, provider, session_id):
        with self.db() as db:
            return self._session_enabled(db, provider, session_id)

    def set_session_enabled(self, token, enabled):
        if type(enabled) is not bool:
            raise ValueError('Session enabled must be a boolean')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT s.provider,s.session_id FROM turn_summaries AS s JOIN turns '
                             'USING(provider,session_id,turn_id) WHERE s.token=?', (token,)).fetchone()
            if row is None:
                raise ValueError('Unknown or expired notification token')
            identity = (row['provider'], row['session_id'])
            db.execute('INSERT OR REPLACE INTO session_preferences(provider,session_id,enabled) VALUES(?,?,?)',
                       identity + (int(enabled),))
            if not enabled:
                # Cancellation is attached to each job so a quick re-enable
                # cannot revive audio the user has already stopped.
                db.execute("UPDATE jobs SET status='cancelled',error='Session speech disabled' "
                           "WHERE provider=? AND session_id=? AND status IN ('pending','speaking')", identity)
                db.execute('UPDATE turn_summaries SET body=NULL WHERE provider=? AND session_id=?', identity)
            return dict(provider=identity[0], session_id=identity[1], enabled=enabled)

    def session_preferences(self):
        with self.db() as db:
            return [dict(provider=row['provider'], session_id=row['session_id'], enabled=bool(row['enabled']))
                    for row in db.execute('SELECT * FROM session_preferences ORDER BY provider,session_id')]

    def begin_turn(self, provider, session_id, turn_id):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO turns VALUES(?,?,?)', (provider, session_id, turn_id))
            # Queued results belong to completed rounds and survive follow-ups.
            # Expire submission tokens without cancelling accepted notifications.
            db.execute('DELETE FROM turn_summaries WHERE provider=? AND session_id=? AND turn_id<>?',
                       (provider, session_id, turn_id))
            db.execute('INSERT OR IGNORE INTO turn_summaries(provider,session_id,turn_id,token) VALUES(?,?,?,?)',
                       (provider, session_id, turn_id, str(uuid.uuid4())))
            return db.execute('SELECT token FROM turn_summaries WHERE provider=? AND session_id=? AND turn_id=?',
                              (provider, session_id, turn_id)).fetchone()['token']

    def stage_summary(self, token, payload, *, cancelled=None, timeout=15):
        from .summary import summary_body
        body = summary_body(payload)
        with self.db(timeout=timeout) as db:
            db.execute('BEGIN IMMEDIATE')
            if cancelled and cancelled():
                raise ValueError('Summary listener is stopping')
            if not self._global_enabled(db):
                raise ValueError('Global speech is disabled; no summary is needed')
            if not self._summary_enabled(db):
                raise ValueError('Summary generation is disabled; no summary is needed')
            session = db.execute('SELECT provider,session_id FROM turn_summaries WHERE token=?', (token,)).fetchone()
            if session is None:
                raise ValueError('Unknown or expired notification token')
            if not self._session_enabled(db, session['provider'], session['session_id']):
                raise ValueError('Session speech is disabled; no summary is needed')
            # Tokens are issued by UserPromptSubmit and invalidated on a new turn.
            if db.execute('UPDATE turn_summaries SET body=?,updated=? WHERE token=?', (body, time.time(), token)).rowcount != 1:
                raise ValueError('Unknown or expired notification token')
            if cancelled and cancelled():
                raise ValueError('Summary listener is stopping')

    def summary_for_turn(self, provider, session_id, turn_id):
        with self.db() as db:
            self._expire_summaries(db)
            # Existing turns from before the no-comment update are registered
            # too. They may read a short reply even without a newly issued token.
            row = db.execute('SELECT s.token,s.body FROM turns AS t LEFT JOIN turn_summaries AS s '
                             'USING(provider,session_id,turn_id) '
                             'WHERE t.provider=? AND t.session_id=? AND t.turn_id=?',
                             (provider, session_id, turn_id)).fetchone()
            return dict(row) if row else None

    def discard_summary(self, provider, session_id, turn_id):
        # Keep the submission token usable when background work resumes, but
        # never announce an earlier waiting summary as the completed result.
        with self.db() as db:
            db.execute('UPDATE turn_summaries SET body=NULL WHERE provider=? AND session_id=? AND turn_id=?',
                       (provider, session_id, turn_id))

    def enqueue(self, provider, session_id, turn_id, body, delay=0):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._global_enabled(db):
                self._suppress_notification(db, provider, session_id, turn_id)
                return None
            if not self._session_enabled(db, provider, session_id):
                self._suppress_notification(db, provider, session_id, turn_id, 'Session speech disabled')
                return None
            if not self._summary_enabled(db):
                body = ''
            current = db.execute('SELECT turn_id FROM turns WHERE provider=? AND session_id=?',
                                 (provider, session_id)).fetchone()
            if current and current['turn_id'] != turn_id:
                return None
            now = time.time()
            db.execute('INSERT OR IGNORE INTO jobs(provider,session_id,turn_id,body,received,ready_after) '
                       'VALUES(?,?,?,?,?,?)', (provider, session_id, turn_id, body, now, now + delay))
            row = db.execute('SELECT id,status FROM jobs WHERE provider=? AND session_id=? AND turn_id=?',
                             (provider, session_id, turn_id)).fetchone()
            return None if row['status'] == 'cancelled' else row['id']

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._expire_summaries(db)
            if not self._global_enabled(db):
                return None
            db.execute("UPDATE jobs SET status='cancelled',error='Session speech disabled' "
                       "WHERE status='pending' AND EXISTS (SELECT 1 FROM session_preferences AS s "
                       "WHERE s.provider=jobs.provider AND s.session_id=jobs.session_id AND s.enabled=0)")
            job = db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if job is None or job['ready_after'] > time.time():
                return None
            db.execute("UPDATE jobs SET status='speaking' WHERE id=?", (job['id'],))
            return dict(job)

    def wait_seconds(self):
        with self.db() as db:
            job = db.execute("SELECT ready_after FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            return None if job is None else max(0, job['ready_after'] - time.time())

    def finish(self, job_id, status, error=None):
        if status not in ('spoken', 'failed', 'uncertain', 'cancelled', 'skipped'):
            raise ValueError('Invalid playback state')
        with self.db() as db:
            # A concurrent disable owns cancellation; the worker cannot overwrite it.
            db.execute("UPDATE jobs SET status=?,error=? WHERE id=? AND status='speaking'", (status, error, job_id))

    def playback_cancelled(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            return row is None or row['status'] != 'speaking' or not self._global_enabled(db)

    def recover_playback(self):
        # Call only after acquiring the exclusive speaker lock.
        with self.db() as db:
            db.execute("UPDATE jobs SET status='uncertain',error='Worker ended before confirming playback' "
                       "WHERE status='speaking'")

    def jobs(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY id')]

    def event(self, session_id, kind, detail):
        with self.db() as db:
            db.execute('INSERT INTO events(created,session_id,kind,detail) VALUES(?,?,?,?)',
                       (time.time(), session_id, kind, str(detail)[:500]))

    def events(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 10')]

    def record_voice_notice(self, provider, session_id, detail, category='voice_download'):
        """Persist a one-time prompt notice; rate-limit identical desktop notices."""
        if category not in ('voice_download', 'media_ducking'):
            raise ValueError('Invalid playback notice category')
        needed, reported = category + '_needed', category + '_reported'
        key, detail, now = provider + ':' + session_id, str(detail)[:500], time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._global_enabled(db) or not self._session_enabled(db, provider, session_id):
                return False
            recent = list(db.execute("SELECT session_id FROM events WHERE detail=? AND created>? "
                                     "AND kind IN (?,?)",
                                     (detail, now - 86400, needed, reported)))
            if not any(row['session_id'] == key for row in recent):
                db.execute("INSERT INTO events(created,session_id,kind,detail) "
                           "VALUES(?,?,?,?)", (now, key, needed, detail))
            return not recent

    def take_voice_notice(self, provider, session_id, category='voice_download'):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id,detail FROM events WHERE session_id=? "
                             "AND kind=? ORDER BY id DESC LIMIT 1",
                             (provider + ':' + session_id, category + '_needed')).fetchone()
            if row is None:
                return ''
            db.execute("UPDATE events SET kind=? WHERE id=?", (category + '_reported', row['id']))
            return row['detail']
