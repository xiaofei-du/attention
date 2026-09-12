#!/bin/bash
# A small launcher for the checked Python uninstaller. No cleanup of user data here.
# Keep this digest in sync with scripts/uninstall.py; the package builder checks it.

main() (
    set -euo pipefail
    if [[ $EUID -eq 0 || $EUID -ne $UID ]]; then
        printf '%s\n' 'Do not run Attention uninstall with sudo/root or elevated privileges.' >&2; exit 1
    fi
    readonly expected_sha256='afed805ffa17bdcdadc4bfe3c439d0a30e7d024763a5b331db76aaae14c36430'
    readonly helper_url='https://api.github.com/repos/xiaofei-du/attention/git/blobs/2ad7cfecb57839f1e15516e9308a4255049a3d32'
    local offline=false scratch='' candidate source_dir='' helper='' interpreter='' executable digest
    local data_root="${ATTENTION_DATA_DIR:-$HOME/Library/Application Support/Attention}"
    local -a arguments=() candidates=()
    case "$(/usr/bin/uname -s)" in
        Darwin) ;;
        Linux) data_root="${ATTENTION_DATA_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/attention}" ;;
        *) printf '%s\n' 'Attention uninstall supports macOS and Linux only.' >&2; exit 1 ;;
    esac
    while (( $# )); do
        case "$1" in
            --offline) offline=true ;;
            --dry-run|--yes) arguments+=("$1") ;;
            --data-dir)
                if (( $# < 2 )) || [[ -z "$2" ]]; then
                    printf '%s\n' '--data-dir requires an Attention data directory.' >&2; exit 2
                fi
                data_root="$2"; arguments+=("$1" "$2"); shift ;;
            --help|-h)
                printf '%s\n' 'Attention uninstall: preview, confirm, then remove Attention from both clients.' \
                    'Usage: bash uninstall.sh [--dry-run | --yes] [--offline] [--data-dir PATH]' \
                    'Quit Codex and Claude Code first. Default: ask in the terminal before deleting.' \
                    '--dry-run: preview only. --yes: explicitly skip confirmation.' \
                    '--offline: use a verified local helper; never download.'
                exit 0 ;;
            *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
        esac
        shift
    done
    # Do not discover executables through the current directory or relative PATH entries.
    local part clean_path='' remaining_path="${PATH:-}:"
    while [[ "$remaining_path" = *:* ]]; do
        part="${remaining_path%%:*}"
        remaining_path="${remaining_path#*:}"
        case "$part" in /*) clean_path="${clean_path:+$clean_path:}$part" ;; esac
    done
    if [[ -z "$clean_path" ]]; then
        printf '%s\n' 'No absolute executable directories in PATH. Nothing was removed.' >&2
        exit 1
    fi
    export PATH="$clean_path"
    for candidate in python3 python3.12 python3.11 python; do
        executable="$(command -v "$candidate" || true)"
        if [[ "$executable" = /* && -f "$executable" && -x "$executable" ]] && \
                "$executable" -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            interpreter="$executable"; break
        fi
    done
    if [[ -z "$interpreter" ]] && executable="$(command -v uv)" && \
            [[ "$executable" = /* && -f "$executable" && -x "$executable" ]]; then
        # Find an existing interpreter only: uninstall never installs Python or packages.
        interpreter="$("$executable" python find --no-project --system --no-config --offline --no-python-downloads 3.12 2>/dev/null || true)"
    fi
    if [[ "$interpreter" != /* || ! -f "$interpreter" || ! -x "$interpreter" ]]; then
        printf '%s\n' 'No usable Python 3.11+ was found. Restore Python or the uv-managed Python used by Attention, then retry. Nothing was removed.' >&2
        exit 1
    fi
    scratch="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/attention-uninstall.XXXXXXXX")"
    # Only these two names in our private temporary directory are ever removed by this shell script.
    trap 'result=$?; /bin/rm -f -- "$scratch/uninstall.py"; /bin/rmdir -- "$scratch"; exit "$result"' EXIT
    no_symlinks() {
        local path="$1"
        [[ "$path" = /* ]] || path="$PWD/$path"
        while [[ "$path" != / && -n "$path" ]]; do
            [[ ! -L "$path" ]] || return 1
            path="${path%/*}"
        done
    }
    verified_copy() {
        [[ -f "$1" ]] && no_symlinks "$1" || return 1
        /bin/cp -- "$1" "$scratch/uninstall.py" || return 1
        # Isolated stdlib code hashes bytes; candidate Python code is never imported.
        digest="$("$interpreter" -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$scratch/uninstall.py")"
        [[ "$digest" = "$expected_sha256" ]]
    }
    if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
        source_dir="${BASH_SOURCE[0]}"
        [[ "$source_dir" = /* ]] || source_dir="$PWD/$source_dir"
        candidates+=("${source_dir%/*}/scripts/uninstall.py")
    fi
    # Fixed roots and one version-directory level, never a recursive disk search.
    candidates+=(
        "${CODEX_HOME:-$HOME/.codex}"/plugins/cache/xiaofei-du/attention/*/scripts/uninstall.py
        "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/xiaofei-du/attention/*/scripts/uninstall.py
        "$data_root"/r/*/scripts/uninstall.py
    )
    for candidate in "${candidates[@]}"; do
        if verified_copy "$candidate"; then helper="$scratch/uninstall.py"; break; fi
    done
    if [[ -z "$helper" ]]; then
        if "$offline"; then
            printf '%s\n' 'No local uninstall helper matched the required SHA-256. Nothing was removed. Use a matching Attention package or retry without --offline.' >&2
            exit 1
        fi
        printf '%s\n' 'Fetching the Attention uninstall helper from GitHub and checking its SHA-256.' >&2
        executable="$(command -v curl || true)"
        if [[ "$executable" != /* || ! -f "$executable" || ! -x "$executable" ]] || ! "$executable" -qfsSL --proto '=https' --proto-redir '=https' \
                --max-time 30 --max-filesize 1048576 -H 'Accept: application/vnd.github.raw+json' "$helper_url" -o "$scratch/uninstall.py"; then
            printf '%s\n' 'Download failed. Nothing was removed. Use the uninstall.sh bundled with Attention for offline removal.' >&2
            exit 1
        fi
        digest="$("$interpreter" -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$scratch/uninstall.py")"
        if [[ "$digest" != "$expected_sha256" ]]; then
            printf '%s\n' 'Uninstall helper SHA-256 mismatch. Nothing was removed. Download a matching launcher and helper from Attention.' >&2
            exit 1
        fi
        helper="$scratch/uninstall.py"
    fi
    "$interpreter" -I "$helper" --interactive ${arguments[@]+"${arguments[@]}"}
)

main "$@"
