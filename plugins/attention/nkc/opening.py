"""Import short local opening sounds without playing them or changing macOS settings."""

import aifc
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


SYSTEM_SOUNDS = Path('/System/Library/Sounds')
INPUT_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aif', '.aiff'}
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 30
PCM_RATE = 22050


def system_sounds():
    return sorted(path.stem for path in SYSTEM_SOUNDS.glob('*.aiff') if path.is_file())


def pcm_frames(path):
    """Read only bounded, normalized PCM; reject missing or damaged saved assets."""
    with aifc.open(str(path), 'rb') as file:
        if (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getcomptype()) != (1, 2, PCM_RATE, b'NONE'):
            raise ValueError('Opening audio must use normalized PCM AIFF')
        frames = file.getnframes()
        if not 0 < frames <= MAX_SECONDS * PCM_RATE:
            raise ValueError('Opening audio must be nonempty and at most 30 seconds; it was not truncated')
        data = file.readframes(frames)
        if len(data) != frames * 2:
            raise ValueError('Opening audio file is incomplete')
        return data


def _convert(source, target, fmt='AIFF', data='BEI16@22050'):
    try:
        subprocess.run(['/usr/bin/afconvert', str(source), str(target), '-f', fmt, '-d', data, '-c', '1'],
                       check=True, capture_output=True, timeout=15)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError('Cannot decode or convert opening audio; the previous opening was kept') from error


def prepare_audio(payload, directory):
    """Validate and copy to an immutable local asset before any selection is saved."""
    if not isinstance(payload, dict):
        raise ValueError('Audio opening requires a JSON object')
    kind = payload.get('type')
    if kind == 'system' and set(payload) == {'type', 'name'}:
        name = payload['name']
        if not isinstance(name, str) or name not in system_sounds():
            raise ValueError('Unknown system sound; choose a name from list-start-sounds')
        source = SYSTEM_SOUNDS / (name + '.aiff')
    elif kind == 'custom' and set(payload) == {'type', 'path'}:
        if not isinstance(payload['path'], str) or not payload['path']:
            raise ValueError('Custom audio requires a local file path')
        source = Path(payload['path']).expanduser().resolve()
        name = source.stem
    else:
        raise ValueError('Audio opening requires type/name for system or type/path for custom')
    if not source.is_file():
        raise ValueError('Opening audio file does not exist or is not a regular file')
    if source.suffix.lower() not in INPUT_EXTENSIONS:
        raise ValueError('Opening audio supports MP3, WAV, M4A and AIFF files')
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError('Opening audio file must be at most 20 MiB')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='import-', dir=str(directory)) as temporary:
        copied = Path(temporary) / ('source' + source.suffix.lower())
        with source.open('rb') as file:
            raw = file.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('Opening audio file must be at most 20 MiB')
        copied.write_bytes(raw)
        normalized = Path(temporary) / 'normalized.aiff'
        _convert(copied, normalized)
        frames = pcm_frames(normalized)
        target = directory / (hashlib.sha256(normalized.read_bytes()).hexdigest() + '.aiff')
        os.replace(normalized, target)
    return {'type': kind, 'name': name, 'file': str(target), 'seconds': len(frames) / (2 * PCM_RATE)}


def preview_audio(payload, output):
    """Produce an audition file without changing the saved opening or auto-playing."""
    output = Path(output).expanduser().resolve()
    if output.suffix.lower() not in ('.wav', '.aiff', '.aif', '.m4a'):
        raise ValueError('Preview output must be WAV, AIFF or M4A')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nkc-preview-', dir=str(output.parent)) as temporary:
        prepared = prepare_audio(payload, Path(temporary) / 'audio')
        ready = Path(temporary) / ('preview' + output.suffix)
        if output.suffix.lower() in ('.aiff', '.aif'):
            shutil.copyfile(prepared['file'], ready)
        else:
            fmt, data = ('WAVE', 'LEI16') if output.suffix.lower() == '.wav' else ('m4af', 'aac')
            _convert(prepared['file'], ready, fmt, data)
        os.replace(ready, output)
    return {'file': str(output), 'seconds': prepared['seconds']}
