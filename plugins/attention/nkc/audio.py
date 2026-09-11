"""Local speech rendering and temporary attenuation of other apps' media."""

import fcntl
import aifc
import os
import platform
import plistlib
import subprocess
import tempfile
import time
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .install import PROJECT
from .language import notification_speech_segments, prepare_voice_inventory, speech_segments
from .opening import pcm_frames
from .summary import notification_text
from .voice_setup import MissingVoice

APP = (Path(os.environ['ATTENTION_BUILD_DIR']) / 'Attention.app' if os.environ.get('ATTENTION_BUILD_DIR')
       else PROJECT / '.build' / 'No Keyboard Code.app')
PLAYER = APP / 'Contents' / 'MacOS' / 'nkc-player'


def build_player():
    if os.environ.get('ATTENTION_BUILD_DIR'):
        if not PLAYER.is_file():
            raise RuntimeError('Attention! native player is missing. Reinstall the plugin.')
        return PLAYER
    PLAYER.parent.mkdir(parents=True, exist_ok=True)
    with (PROJECT / '.build' / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        descriptor, temporary = tempfile.mkstemp(prefix='nkc-player-', dir=str(PLAYER.parent))
        os.close(descriptor)
        try:
            architecture = platform.machine()
            if architecture not in ('arm64', 'x86_64'):
                raise RuntimeError('Native player requires an Apple Silicon or Intel Mac')
            subprocess.run(['xcrun', 'clang', '-target', architecture + '-apple-macos14.2',
                            '-fobjc-arc', '-Wall', '-Wextra', '-Werror', str(PROJECT / 'native' / 'player.m'),
                            str(PROJECT / 'native' / 'duck.m'),
                            '-framework', 'Foundation', '-framework', 'AVFAudio', '-framework', 'CoreAudio',
                            '-o', temporary], check=True, timeout=60, capture_output=True)
            os.chmod(temporary, 0o755)
            os.replace(temporary, PLAYER)
            (APP / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'local.no-keyboard-code.audio',
                'CFBundleExecutable': 'nkc-player',
                'CFBundleName': 'No Keyboard Code',
                'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1',
                'CFBundleShortVersionString': '0.1.0',
                'LSMinimumSystemVersion': '14.2',
                'LSUIElement': True,
                'NSAudioCaptureUsageDescription':
                    'Temporarily lower other apps’ media while a task summary speaks. '
                    'System audio is processed live on this Mac, without microphone access, saving it, or sending it anywhere.',
            }))
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(APP)],
                           check=True, timeout=30, capture_output=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError('Native player build failed: ' + error.stderr.decode(errors='replace')[:1500]) from error
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return PLAYER


class AudioProcessError(RuntimeError):
    def __init__(self, returncode, detail):
        self.returncode = returncode
        super().__init__('Audio process failed: ' + detail)


class MediaDuckingWarning(UserWarning):
    pass


def run_process(command, is_cancelled, timeout, lock_fd=None):
    if is_cancelled():
        return False
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                   pass_fds=() if lock_fd is None else (lock_fd,))
        started = time.monotonic()
        try:
            while process.poll() is None:
                if is_cancelled():
                    return False
                if time.monotonic() - started > timeout:
                    raise RuntimeError('Audio process timeout')
                time.sleep(0.05)
            if process.returncode:
                errors.seek(0)
                raise AudioProcessError(process.returncode, errors.read(1500).decode(errors='replace').strip())
            return True
        finally:
            if process.poll() is None:
                # Wait for the native player's cleanup before the queue advances.
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def render_speech(text, settings, output, is_cancelled=lambda: False, lock_fd=None, *, session_name=None):
    """Synthesize all voices to one PCM file before acquiring media attenuation."""
    if is_cancelled():
        return False
    output = Path(output)
    suffix = output.suffix.lower()
    if suffix not in ('.aiff', '.aif', '.wav', '.m4a'):
        raise ValueError('Audio output must be AIFF, WAV, or M4A')
    output.parent.mkdir(parents=True, exist_ok=True)
    spoken = text if session_name is None else notification_text(text, settings, session_name)
    segments = []
    if spoken.strip():
        prepare_voice_inventory(settings)
        segments = (speech_segments(text, settings) if session_name is None else
                    notification_speech_segments(text, settings, session_name))
    if not segments and not settings.get('start_audio'):
        raise MissingVoice('No speakable notification content is available')
    deadline = time.monotonic() + 30
    with tempfile.TemporaryDirectory(prefix='nkc-render-', dir=str(output.parent)) as directory:
        directory = Path(directory)
        joined = directory / 'joined.aiff'
        failed = threading.Event()

        def cancelled():
            return failed.is_set() or is_cancelled()

        def synthesize(item):
            index, (voice, segment) = item
            try:
                if cancelled():
                    return None
                source, rendered = directory / (str(index) + '.txt'), directory / (str(index) + '.aiff')
                source.write_text(segment, encoding='utf-8')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('Speech rendering timeout')
                if not run_process(['/usr/bin/say', '-v', voice, '-r', str(settings['rate']),
                                    '--file-format=AIFF', '--data-format=BEI16@22050', '--channels=1',
                                    '-o', str(rendered), '-f', str(source)], cancelled,
                                   timeout=remaining, lock_fd=lock_fd):
                    failed.set()
                    return None
                return rendered
            except BaseException:
                failed.set()
                raise

        # At most two silent synthesizers run concurrently. Join waits for every
        # child to finish/clean up before any playback or temporary-file cleanup.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(synthesize, item) for item in enumerate(segments)]
            rendered_files = [future.result() for future in futures]
        if cancelled() or any(path is None for path in rendered_files):
            return False
        with aifc.open(str(joined), 'wb') as target:
            target.setparams((1, 2, 22050, 0, b'NONE', b'not compressed'))
            if settings.get('start_audio'):
                if is_cancelled():
                    return False
                target.writeframes(pcm_frames(settings['start_audio']['file']))
                target.writeframes(b'\0\0' * 3307)  # A short pause between the sound and speech.
            for audio in rendered_files:
                if is_cancelled():
                    return False
                with aifc.open(str(audio), 'rb') as rendered:
                    if (rendered.getnchannels(), rendered.getsampwidth(), rendered.getframerate(),
                            rendered.getcomptype()) != (1, 2, 22050, b'NONE'):
                        raise RuntimeError('Speech segments have incompatible audio formats')
                    if rendered.getnframes() == 0:
                        raise RuntimeError('Speech segment is empty')
                    target.writeframes(rendered.readframes(rendered.getnframes()))
        if is_cancelled():
            return False
        ready = joined
        if suffix in ('.wav', '.m4a'):
            ready = directory / ('converted' + suffix)
            file_format, data_format = ('WAVE', 'LEI16') if suffix == '.wav' else ('m4af', 'aac')
            if not run_process(['/usr/bin/afconvert', str(joined), str(ready), '-f', file_format,
                                '-d', data_format], is_cancelled, timeout=30, lock_fd=lock_fd):
                return False
        os.replace(ready, output)
    return True


def speak(text, settings, is_cancelled, player=PLAYER, lock_fd=None, *, session_name=None):
    if not Path(player).is_file():
        raise RuntimeError('Native player missing; run run.py build before enabling speech')
    with tempfile.TemporaryDirectory(prefix='nkc-speech-') as directory:
        audio = Path(directory) / 'summary.aiff'
        if not render_speech(text, settings, audio, is_cancelled, lock_fd, session_name=session_name):
            return False
        # Exit 75 means the relay was torn down BEFORE any speech started.
        # Other failures may follow partial speech and must never replay it.
        if settings.get('duck_media', False):
            try:
                return run_process([str(player), '--duck', str(audio)], is_cancelled, timeout=150, lock_fd=lock_fd)
            except AudioProcessError as error:
                if error.returncode != 75:
                    raise
                if is_cancelled():
                    return False
                warnings.warn('Media ducking is unavailable; continuing with ordinary playback. '
                              'Check macOS system-audio permission or turn off duck_media.', MediaDuckingWarning)
        return run_process([str(player), str(audio)], is_cancelled, timeout=150, lock_fd=lock_fd)
