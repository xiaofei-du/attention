---
name: attention-help
description: Use when the user asks how to use Attention, Attention help, Attention 怎麼用, or about its starter options, voices, notification switches, summary preferences, or lowering other media.
---

# Attention help

Answer in the user's language. For general help, give a short introduction,
starter choices, and a few natural-language examples. For a specific question,
explain just that feature. When introducing media lowering, state that it is
optional, off on new installs, and may need system-audio permission.
An example or help request does not authorize changes,
downloads, permission requests, or previews. Use read tools only when current
settings or this Mac's available options are needed; never invent their values.

## What it does

Attention reads updates when a Codex or Claude Code turn finishes. The original
agent chooses direct speech for suitable short replies or writes a conversational
summary covering task context, progress, and the next action or decision. Multiple
sessions share one queue. No extra LLM or cloud TTS call is used. Currently macOS
14.2+ only; at least one usable installed system voice is needed for speech.

## Starter choices

The starter plays before the update. Explain all four when introducing options:

| Choice | Natural request | Behavior |
|---|---|---|
| Text | “開場改成『你好美女』” | Speak those exact words until explicitly changed. |
| Apple alert sound | “列出 Apple 自帶提示音” | List this Mac's sounds; after selection, play the sound then speak the update. |
| Custom audio file | “用這個 MP3 當開場” + local file | Play the imported clip then speak the update. |
| None | “不要開場” | Skip the starter and continue to the update. |

Audio replaces the text starter. Custom MP3, WAV, M4A, AIF/AIFF files must be at
most 30 seconds and 20 MiB; they are validated and copied locally. A local path
is required; ask for the file/path if missing. There is no plugin upload UI.
Optional session-name reporting follows the starter and has its own switch.

## More examples and controls

| User request | Existing MCP control |
|---|---|
| “現在設定是什麼？” | `get_status` |
| “有哪些音色？” / “換男聲” | `list_voices` / `set_voice_preferences(gender="male")` |
| “播報時把 Spotify 等背景媒體降低” | `set_voice_preferences(duck_media=true)` |
| “列出開場音效” | `get_starter_sound_options` |
| “開場改成……” / “先報 session 名稱” | `set_starter_options` (opening / announce_session_name) |
| “關閉這個 session 語音” | `set_session_enabled(enabled=false)` |
| “全域關閉語音” | `set_global_enabled(enabled=false)` |
| “摘要多講下一步” | `set_summary_preferences(focus="next_steps")` |
| “關閉摘要，只播開場” / “重新開啟摘要” | `set_summary_preferences(enabled=false)` / `enabled=true` |
| “清掉待播通知” | `clear_queue` |

Set only explicitly requested fields. Session controls require the current
native call context; never guess or supply a session ID or token. Use the installed tool
schemas or the hook's CLI fallback, not invented commands.

New installs use “hey boss”, speech on, session-name reporting off, and media
lowering off. Existing preferences survive updates. Media lowering temporarily
reduces other apps during playback and restores them afterward; enabling it may
require macOS system-audio permission, never microphone access. If unavailable,
ordinary playback continues with a notice. Missing voices get download guidance;
coding continues. Auto voice mode follows sentence language using installed voices.

Global off stops current speech, clears queued/staged updates, and discards new
completions. Re-enabling preserves muted sessions and never replays old updates.
A session cannot override global off. Clearing the queue lets current speech finish.
Summary length is a soft 10–90 second guide; no arbitrary summary prompt is accepted.

Summary `enabled` is a shared switch for all sessions, default true. False clears
ALL pending notifications and staged summaries and stops current reply-content
speech. Future completions play only the starter and optional existing session
name; no reply is read or summarized. If neither can play, the notification is
silent. Re-enable preserves other preferences without restoring old content or
overriding mute. This is not the per-session speech switch. An already-playing
starter-only notification can finish. The notification path needs no LLM; local
text-to-speech and natural-language setting controls are separate. Ordinary summary-off
rounds inject no hook context or welcome. Old sessions receive one revocation at
their next prompt; host history cannot be erased. MCP/help metadata may still use
context, so do not promise zero total tokens. Re-enable needs no token and restores
summary instructions at the next prompt. Do not reuse old submission commands.

If hooks/tools are missing, suggest reloading the client and reviewing the
Attention plugin's UserPromptSubmit and Stop hooks in Codex. Claude Code also
uses a silent PreToolUse hook for session controls. It does not inject context,
rewrite inputs, approve changes or ask the model to retry. Session identity is
resolved internally for set_session_enabled(enabled) and get_status(scope="session").
If identity is unavailable, reload Attention/check the Claude hook; never guess an
ID, change another session or automatically retry a cancelled confirmation.