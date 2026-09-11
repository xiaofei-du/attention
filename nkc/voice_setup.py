"""Missing voices are installation notices, separate from playback failures."""

import subprocess

DOWNLOAD_HELP = {
    'settings_path': 'System Settings > Accessibility > Read & Speak > System voice',
    'instructions': 'Open the info button, choose a language and download an available voice. '
                    'Some languages or voice types may not be offered by Apple.',
    'url': 'https://support.apple.com/guide/mac-help/mchlp2290/mac',
}
DOWNLOAD_GUIDANCE = ('To download a voice, open ' + DOWNLOAD_HELP['settings_path'] +
                     ' > info, then choose a language and an available voice. '
                     'Availability varies by language.')


class MissingVoice(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason + '. ' + DOWNLOAD_GUIDANCE)


class VoiceDownloadWarning(RuntimeWarning):
    """Playback can continue, but a preferred or optional voice needs a download."""


def show_voice_notice(message):
    # Values are argv data, never AppleScript source. No alert sound, focus
    # change, microphone, download or automatic Settings navigation.
    script = ('on run argv\n'
              'display notification (item 1 of argv) with title "Attention! playback notice"\n'
              'end run')
    subprocess.run(['/usr/bin/osascript', '-e', script, str(message)],
                   check=True, capture_output=True, timeout=5)


def refresh_voice_inventory():
    from . import language
    language._inventory_snapshot = None
    language.installed_voices.cache_clear()
    language.installed_voice_metadata.cache_clear()
    language.native_voice_metadata.cache_clear()
