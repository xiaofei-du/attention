"""Choose installed macOS voices using local sentence-language detection."""

import fcntl
import json
import os
import re
import subprocess
import tempfile
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from functools import lru_cache

from .install import PROJECT
from .summary import SESSION_LABEL, notification_text, opening_prefix, spoken_session_name
from .voice_setup import DOWNLOAD_HELP, DOWNLOAD_GUIDANCE, MissingVoice, VoiceDownloadWarning

DETECTOR = Path(os.environ.get('ATTENTION_BUILD_DIR', str(PROJECT / '.build'))) / 'nkc-language'
# Prefer conversational voices over novelty/character voices in `say -v ?`.
PREFERRED = {
    'en': 'Samantha', 'zh': 'Meijia', 'ja': 'Kyoko', 'ko': 'Yuna',
    'fr': 'Thomas', 'de': 'Anna', 'es': 'Mónica', 'it': 'Alice',
    'pt': 'Joana', 'nl': 'Xander', 'ru': 'Milena', 'ar': 'Majed',
}
_inventory_snapshot = None


def build_detector():
    if os.environ.get('ATTENTION_BUILD_DIR'):
        if not DETECTOR.is_file():
            raise RuntimeError('Attention! language helper is missing. Reinstall the plugin.')
        return DETECTOR
    source = PROJECT / 'native' / 'language.m'
    DETECTOR.parent.mkdir(parents=True, exist_ok=True)
    with (DETECTOR.parent / 'language-build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if DETECTOR.exists() and DETECTOR.stat().st_mtime >= source.stat().st_mtime:
            return DETECTOR
        fd, temporary = tempfile.mkstemp(prefix='nkc-language-', dir=str(DETECTOR.parent))
        os.close(fd)
        try:
            subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                            str(source), '-framework', 'Foundation', '-framework', 'NaturalLanguage',
                            '-framework', 'AppKit', '-o', temporary],
                           check=True, capture_output=True, timeout=30)
            os.chmod(temporary, 0o755)
            os.replace(temporary, DETECTOR)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return DETECTOR


@lru_cache(maxsize=1)
def installed_voices():
    if _inventory_snapshot is not None:
        return _inventory_snapshot['voices']
    output = subprocess.run(['/usr/bin/say', '-v', '?'], check=True, capture_output=True,
                            text=True, timeout=10).stdout
    voices = {}
    for line in output.splitlines():
        # Apple emits ICU identifiers such as zh_CN_U_SD@sd=cnsn as well as
        # simple language/region pairs. Keep the entire locale token eligible;
        # speech routing needs only its base language, metadata retains locale.
        match = re.match(r'(.+?)\s+([a-z]{2,3})(?:[-_@][^\s]+)?\s+#', line, flags=re.IGNORECASE)
        if match:
            voices[match.group(1).strip()] = match.group(2).lower()
    if not voices:
        raise MissingVoice('No installed speech voices found')
    return voices


@lru_cache(maxsize=1)
def native_voice_metadata():
    result = subprocess.run([str(build_detector()), '--voices'], check=True,
                            capture_output=True, text=True, timeout=10)
    records = json.loads(result.stdout)
    if not isinstance(records, list):
        raise ValueError('Invalid voice metadata')
    return records


@lru_cache(maxsize=1)
def installed_voice_metadata():
    if _inventory_snapshot is not None:
        return _inventory_snapshot['metadata']
    installed = installed_voices()
    records = native_voice_metadata()
    catalog = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('name'), str):
            raise ValueError('Invalid voice metadata record')
        name = record['name']
        if name in installed:
            if record.get('gender') not in ('male', 'female', 'unknown') or not isinstance(record.get('locale'), str):
                raise ValueError('Invalid voice metadata attributes')
            catalog.append(dict(record, language=installed[name]))
    if not catalog:
        raise RuntimeError('No installed voice metadata found')
    return catalog


def prepare_voice_inventory(settings):
    """Overlap independent native queries; keep the existing gender fallback."""
    if _inventory_snapshot is not None:
        return
    if settings.get('voice_gender', 'default') == 'default':
        installed_voices()
        return
    with ThreadPoolExecutor(max_workers=2) as pool:
        voices = pool.submit(installed_voices)
        metadata = pool.submit(native_voice_metadata)
        voices.result()
        try:
            metadata.result()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass  # gender_voice reports unavailable metadata and keeps the voice.


def preferred_voices(settings, voices):
    preferred = dict(PREFERRED, en=settings.get('english_voice', 'Samantha'))
    configured = settings.get('voice', 'Meijia')
    if configured in voices and voices[configured] != 'en':
        preferred[voices[configured]] = configured
    return preferred


def base_voice(language, preferred, voices):
    voice = preferred.get(language)
    if voice not in voices or voices.get(voice) != language:
        voice = next((name for name, code in voices.items() if code == language), None)
    return voice


def gender_voice(voice, language, settings, metadata_cache=None):
    gender = settings.get('voice_gender', 'default')
    if gender == 'default':
        return voice
    if gender not in ('male', 'female'):
        raise ValueError('Voice gender must be default, male or female')
    # Cache failures for this one operation too, so a failed native helper isn't
    # retried once per sentence/language. A future notification can try again.
    cache = {} if metadata_cache is None else metadata_cache
    if 'catalog' not in cache:
        try:
            cache['catalog'] = installed_voice_metadata()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            cache['catalog'] = None
    catalog = cache['catalog']
    if catalog is None:
        warnings.warn('Voice gender metadata unavailable; keeping ' + voice, RuntimeWarning)
        return voice
    voices = installed_voices()
    candidates = {item['name'] for item in catalog
                  if item['gender'] == gender and voices.get(item['name']) == language}
    # Respect a matching explicit voice first. Daniel is a conversational English
    # default; every candidate is still checked against Apple's gender metadata.
    for candidate in (voice, 'Daniel' if language == 'en' and gender == 'male' else PREFERRED.get(language)):
        if candidate in candidates:
            return candidate
    if candidates:
        return sorted(candidates)[0]
    warnings.warn('No installed ' + gender + ' voice identified by macOS for ' + language +
                  '; keeping ' + voice + '. ' + DOWNLOAD_GUIDANCE, VoiceDownloadWarning)
    return voice


def voice_report(settings):
    """Report effective choices without playing audio or rewriting named voices."""
    report = {'voice_gender': settings.get('voice_gender', 'default'),
              'voice_mode': settings.get('voice_mode', 'auto'), 'languages': {}, 'warnings': []}
    try:
        voices = installed_voices()
    except MissingVoice as notice:
        report.update(status='needs_voice_download', message=str(notice), download_help=DOWNLOAD_HELP)
        report['warnings'].append(str(notice))
        return report
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        report['warnings'].append('Cannot inspect installed voices; preference is saved but availability is unverified')
        return report
    preferred = preferred_voices(settings, voices)
    if settings.get('voice_mode') == 'fixed':
        voice = settings['voice']
        if voice not in voices:
            notice = MissingVoice('The selected voice is not installed: ' + voice)
            report.update(status='needs_voice_download', message=str(notice), download_help=DOWNLOAD_HELP)
            report['warnings'].append(str(notice))
            return report
        bases = {voices.get(voice, 'und'): voice}
    else:
        bases = {lang: base_voice(lang, preferred, voices) for lang in sorted(set(voices.values()))}
    cache = {}
    for lang, original in bases.items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            chosen = gender_voice(original, lang, settings, cache)
        report['languages'][lang] = {'voice': chosen, 'original_voice': original,
                                    'matched_preference': not bool(caught)}
        report['warnings'].extend(str(item.message) for item in caught)
        if any(isinstance(item.message, VoiceDownloadWarning) for item in caught):
            report['download_help'] = DOWNLOAD_HELP
    return report


def detect_languages(sentences):
    result = subprocess.run([str(build_detector())], input=json.dumps(sentences, ensure_ascii=False),
                            check=True, capture_output=True, text=True, timeout=10)
    languages = json.loads(result.stdout)
    if not isinstance(languages, list) or len(languages) != len(sentences):
        raise RuntimeError('Invalid language detector result')
    return languages


def speech_segments(text, settings):
    if not text.strip():
        raise ValueError('No speech text')
    if settings.get('voice_mode', 'auto') == 'fixed':
        voice = settings['voice']
        voices = installed_voices()
        if voice not in voices:
            raise MissingVoice('The selected voice is not installed: ' + voice)
        if settings.get('voice_gender', 'default') != 'default':
            voice = gender_voice(voice, voices[voice], settings)
        return [(voice, text)]
    # Preserve spaces and decimal versions. English identifiers inside a Chinese
    # sentence stay with its voice rather than switching word by word.
    sentences = re.findall(r'.*?(?:[。！？!?]+\s*|\.(?=\s|$)\s*|$)', text, flags=re.DOTALL)
    sentences = [sentence for sentence in sentences if sentence]
    languages = detect_languages(sentences)
    voices = installed_voices()
    preferred = preferred_voices(settings, voices)
    segments = []
    cache = {}
    for sentence, language in zip(sentences, languages):
        if re.search(r'[\u3040-\u30ff]', sentence):
            language = 'ja'
        elif re.search(r'[\uac00-\ud7af]', sentence):
            language = 'ko'
        elif re.search(r'[\u3400-\u9fff]', sentence) and language.split('-')[0] not in ('ja', 'ko'):
            language = 'zh'
        elif sentence.strip().startswith('Hello, ') or sentence.strip() == 'Hello。':
            language = 'en'
        elif re.fullmatch(r'(?i)\s*(?:ok|okay)[.!?\s]*', sentence):
            # A common acknowledgment shared by many languages; macOS otherwise
            # labels "OK." as Polish. Keep this English spelling predictable.
            language = 'en'
        language = language.split('-')[0]
        voice = base_voice(language, preferred, voices)
        if voice is None:
            if not any(character.isalpha() for character in sentence):
                voice = segments[-1][0] if segments else base_voice('en', preferred, voices)
                if voice is None:
                    raise MissingVoice('No installed voice for detected language: ' + language)
            else:
                raise MissingVoice('No installed voice for detected language: ' + language)
        else:
            voice = gender_voice(voice, language, settings, cache)
        if segments and segments[-1][0] == voice:
            segments[-1] = (voice, segments[-1][1] + sentence)
        else:
            segments.append((voice, sentence))
    return segments


def notification_speech_segments(body, settings, session_name=''):
    """Route the session announcement separately from the opening and body.

    Names come from provider metadata, never from parsing the spoken body.
    All parts use the normal voice preferences, without requiring English for
    the label. Adjacent equal voices share one synthesis for continuous prosody.
    """
    name = spoken_session_name(session_name) if settings.get('announce_session_name') else ''
    if not name:
        return speech_segments(notification_text(body, settings), settings)
    # Use the same validation/normalization as the ordinary notification path.
    body = notification_text(body, dict(settings, start='', start_audio=None,
                                        announce_session_name=False))
    parts = []
    notices = []
    start = '' if settings.get('start_audio') else settings['start']
    if start:
        try:
            parts.extend(speech_segments(opening_prefix(start, SESSION_LABEL), settings))
        except MissingVoice:
            notices.append('No installed voice for the spoken opening; skipped that opening')
    try:
        parts.extend(speech_segments(SESSION_LABEL + name + '. ', settings))
    except MissingVoice:
        # Never leave a bare label that could make the body sound like a title.
        notices.append('No installed voice for the session name; skipped the session announcement')
    if notices:
        warnings.warn('; '.join(notices) + '. ' + DOWNLOAD_GUIDANCE, VoiceDownloadWarning)
    if body:
        parts.extend(speech_segments(body, settings))
    segments = []
    for voice, text in parts:
        if segments and segments[-1][0] == voice:
            segments[-1] = (voice, segments[-1][1] + text)
        else:
            segments.append((voice, text))
    return segments
