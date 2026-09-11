"""Local control operations. No summary generation, playback, or worker startup."""

from .language import installed_voice_metadata, voice_report
from .opening import system_sounds
from .voice_setup import DOWNLOAD_HELP, MissingVoice
from .voice_cache import voice_inventory


def starter_options(settings):
    opening = settings['start_audio']
    if opening is None:
        opening = {'type': 'text', 'text': settings['start']} if settings['start'] else {'type': 'none'}
    return {'opening': opening, 'announce_session_name': settings['announce_session_name']}


def voice_preferences(settings):
    return {key: settings[key] for key in ('voice', 'english_voice', 'voice_mode', 'voice_gender', 'rate', 'duck_media')}


class Controls:
    def __init__(self, store):
        self.store = store

    def get_status(self, token=None):
        session = self.store.session_for_token(token) if token is not None else None
        settings = self.store.settings()
        if session is not None:
            session['effective_enabled'] = session['enabled'] and settings['global_voice_enabled']
        return {'global_enabled': settings['global_voice_enabled'], 'session': session,
                'starter': starter_options(settings), 'voice_preferences': voice_preferences(settings),
                'summary_preferences': self.store.summary_preferences(), 'queue': self.store.queue_status()}

    def list_voices(self):
        try:
            with voice_inventory(self.store.root, force=True):
                return {'voices': installed_voice_metadata()}
        except MissingVoice as notice:
            return {'voices': [], 'status': 'needs_voice_download', 'message': str(notice),
                    'download_help': DOWNLOAD_HELP}

    def set_voice_preferences(self, **preferences):
        self.store.set_voice_preferences(**preferences)
        settings = self.store.settings()
        if set(preferences) == {'duck_media'}:
            return {'voice_preferences': voice_preferences(settings),
                    'availability': {'status': 'unchanged'},
                    'message': ('Lowering other media may request macOS system-audio permission at next playback. '
                                'If unavailable, ordinary playback continues. Microphone access is not used.'
                                if settings['duck_media'] else 'Ordinary playback; system audio is not captured.')}
        try:
            with voice_inventory(self.store.root, force=True):
                availability = voice_report(settings)
        except MissingVoice as notice:
            availability = {'status': 'needs_voice_download', 'message': str(notice),
                            'download_help': DOWNLOAD_HELP}
        return {'voice_preferences': voice_preferences(settings), 'availability': availability}

    def get_starter_sound_options(self):
        return {'sounds': system_sounds(), 'custom_audio': {
            'extensions': ['mp3', 'wav', 'm4a', 'aif', 'aiff'], 'max_seconds': 30,
            'max_bytes': 20 * 1024 * 1024, 'source': 'local file path'}}

    def set_starter_options(self, **options):
        self.store.set_starter_options(**options)
        return starter_options(self.store.settings())

    def set_global_enabled(self, enabled):
        self.store.set_global_enabled(enabled)
        return {'global_enabled': self.store.global_enabled()}

    def set_session_enabled(self, token, enabled):
        result = self.store.set_session_enabled(token, enabled)
        result['effective_enabled'] = result['enabled'] and self.store.global_enabled()
        return result

    def set_summary_preferences(self, **preferences):
        return self.store.set_summary_preferences(**preferences)

    def clear_queue(self):
        return {'cleared': self.store.clear_queue()}
