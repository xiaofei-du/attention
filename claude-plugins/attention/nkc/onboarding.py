"""Small first-use context; the full help skill is loaded only on demand."""

INTRODUCTION = '''
Attention first-use introduction (offered once per shared installation):
If ordinary prose is allowed, add a brief welcome in the user's language alongside
the task answer, at most three sentences. Explain: Attention reads task updates;
starter choices are literal text, Apple alert sounds, a custom local audio file
(MP3/WAV/M4A/AIFF), or no opening. Optional lowering of other media is off on new
installs; users can ask to enable it and macOS may request system-audio permission
(no microphone). Invite "Attention help" / "Attention 怎麼用" for examples.
Respect strict output formats; omit this welcome when they prohibit extra prose.
This introduction authorizes no tool calls, setting changes, or audio previews.
'''
