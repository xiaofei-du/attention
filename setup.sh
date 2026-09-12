#!/bin/bash
# Bootstrap only: verify the helper, prepare uv, delegate to native plugin managers.
# Fixed pins are maintained by scripts/update_setup_command.py.

main() (
    set -euo pipefail
    local client='' install_uv=false dry_run=false arg
    local -a args=()
    while (( $# )); do
        case "$1" in
            --client)
                (( $# >= 2 )) || { printf '%s\n' '--client needs codex, claude or both.' >&2; exit 2; }
                client="$2"; shift
                case "$client" in codex|claude|both) ;; *) printf '%s\n' 'Choose --client codex, claude or both.' >&2; exit 2 ;; esac
                args+=(--client "$client") ;;
            --install-uv) install_uv=true ;;
            --update) args+=(--update) ;;
            --dry-run) dry_run=true; args+=(--dry-run) ;;
            --help|-h)
                printf '%s\n' 'Attention setup: install the native Codex and/or Claude Code plugin.' \
                    'Usage: bash setup.sh [--client codex|claude|both] [--dry-run] [--install-uv]' \
                    'Without --client, choose in the terminal. Existing plugins/settings are preserved.' \
                    '--install-uv: explicitly allow installing missing uv; otherwise ask first.' \
                    '--update: update existing enabled plugins instead of installing; default to available clients.' \
                    '--dry-run: preview; never install uv, marketplaces or plugins.'
                exit 0 ;;
            *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
        esac
        shift
    done
    if [[ $EUID -eq 0 || $EUID -ne $UID ]]; then
        printf '%s\n' 'Run Attention setup without sudo/root or elevated privileges.' >&2; exit 1
    fi
    if [[ "$(/usr/bin/uname -s)" != Darwin ]]; then
        printf '%s\n' 'Attention requires macOS 14.2 or later. Nothing was installed.' >&2; exit 1
    fi
    local version major minor patch
    version="$(/usr/bin/sw_vers -productVersion)"
    [[ "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { printf '%s\n' 'Could not check macOS version.' >&2; exit 1; }
    IFS=. read -r major minor patch <<< "$version"
    if (( 10#$major < 14 || (10#$major == 14 && 10#$minor < 2) )); then
        printf '%s\n' 'Attention requires macOS 14.2 or later. Nothing was installed.' >&2; exit 1
    fi
    case "$(/usr/bin/uname -m)" in arm64|x86_64) ;; *) printf '%s\n' 'Unsupported Mac architecture.' >&2; exit 1 ;; esac
    # Literal absolute PATH entries only; never discover a program from the current project.
    local part remaining="${PATH:-}:" clean_path=''
    while [[ "$remaining" = *:* ]]; do
        part="${remaining%%:*}"; remaining="${remaining#*:}"
        case "$part" in /*) clean_path="${clean_path:+$clean_path:}$part" ;; esac
    done
    export PATH="$clean_path"
    find_executable() {
        local found
        found="$(command -v "$1" || true)"
        [[ "$found" = /* && -f "$found" && -x "$found" ]] || return 1
        printf '%s\n' "$found"
    }
    local selected available=false
    for selected in codex claude; do
        if find_executable "$selected" >/dev/null; then available=true
        elif [[ "$client" = "$selected" || "$client" = both ]]; then
            printf '%s\n' "$selected is not on PATH. Make its terminal command available, then rerun setup." >&2; exit 1
        fi
    done
    if ! "$available"; then
        printf '%s\n' 'Install Codex or Claude Code and make its terminal command available first.' >&2; exit 1
    fi
    local uv='' brew='' answer=''
    uv="$(find_executable uv || true)"
    if [[ -z "$uv" ]] && "$dry_run"; then
        printf '%s\n' 'Would first need uv, then install the selected native plugins. Nothing was installed.'; exit 0
    fi
    if [[ -z "$uv" ]]; then
        brew="$(find_executable brew || true)"
        printf '%s\n' 'Attention needs uv to manage its private Python environment.'
        if [[ -n "$brew" ]]; then
            printf '%s\n' 'Setup can run brew install uv using your existing Homebrew.'
        else
            printf '%s\n' 'Setup can use Astral’s verified uv 0.12.10 installer.' \
                'It installs into ~/.local/bin and updates your shell PATH. No Homebrew or sudo is needed.'
        fi
        if ! "$install_uv"; then
            if ! { printf 'Install uv? Type yes to continue: ' > /dev/tty; read -r answer < /dev/tty; } 2>/dev/null; then
                printf '%s\n' 'uv is missing. Run in a terminal to approve installation, or pass --install-uv.' >&2; exit 1
            fi
            if [[ "$answer" != yes ]]; then printf '%s\n' 'Cancelled. Nothing was installed.'; exit 0; fi
        fi
    fi
    local scratch helper='' source_dir='' digest
    scratch="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/attention-setup.XXXXXXXX")"
    trap 'result=$?; /bin/rm -f -- "$scratch/setup.py" "$scratch/uv-install.sh" "$scratch/sha256sum"; /bin/rmdir -- "$scratch"; exit "$result"' EXIT
    readonly helper_sha256='cb4009bd1396084ab737102761910bc58e6c1fb90849369ab656a2990fd1ecc7'
    readonly helper_url='https://api.github.com/repos/xiaofei-du/attention/git/blobs/880e72bf841841a9aea9149be4822a9b7c467a5c'
    checksum() {
        digest="$(/usr/bin/env -u PERL5OPT -u PERL5LIB /usr/bin/shasum -a 256 "$1")"
        [[ "${digest%% *}" = "$2" ]] || { printf '%s\n' 'SHA-256 mismatch. Downloaded code was not run.' >&2; return 1; }
    }
    download() {
        /usr/bin/curl -qfsSL --proto '=https' --proto-redir '=https' --max-time 60 --max-filesize 1048576 \
            -H 'Accept: application/vnd.github.raw+json' "$1" -o "$2" || {
                printf '%s\n' 'Download failed. Check your connection and rerun setup.' >&2; return 1;
            }
    }
    if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
        source_dir="${BASH_SOURCE[0]}"
        [[ "$source_dir" = /* ]] || source_dir="$PWD/$source_dir"
        source_dir="${source_dir%/*}"
    fi
    helper="$scratch/setup.py"
    if [[ -n "$source_dir" && -f "$source_dir/scripts/setup.py" ]]; then
        /bin/cp -- "$source_dir/scripts/setup.py" "$helper"
    else
        printf '%s\n' 'Fetching the Attention setup helper and checking its SHA-256.'
        download "$helper_url" "$helper"
    fi
    checksum "$helper" "$helper_sha256"
    if [[ -z "$uv" ]]; then
        if [[ -n "$brew" ]]; then
            HOMEBREW_NO_AUTO_UPDATE=1 "$brew" install uv || { printf '%s\n' 'uv installation failed. No plugins were installed.' >&2; exit 1; }
            uv="$(find_executable uv || true)"
        else
            download 'https://astral.sh/uv/0.12.10/install.sh' "$scratch/uv-install.sh"
            checksum "$scratch/uv-install.sh" 'a3196b75f697a1adaa5e4af34ffba7629c710931ab1dac33bab59ecf228080bb'
            # Astral skips binary checks if sha256sum is absent. Supply it using
            # macOS shasum so every supported Mac checks the archive as well.
            printf '%s\n' '#!/bin/sh' 'exec /usr/bin/shasum -a 256 "$@"' > "$scratch/sha256sum"
            /bin/chmod 700 "$scratch/sha256sum"
            # No environment override can change the download source or install root.
            /usr/bin/env -i HOME="$HOME" PATH="$scratch:/usr/bin:/bin:/usr/sbin:/sbin" \
                UV_INSTALL_DIR="$HOME/.local/bin" UV_DISABLE_UPDATE=1 /bin/sh "$scratch/uv-install.sh" || {
                    printf '%s\n' 'uv installation failed. No plugins were installed.' >&2; exit 1;
                }
            uv="$HOME/.local/bin/uv"
            export PATH="$HOME/.local/bin:$PATH"
            printf '%s\n' 'uv installed. Restart your terminal/apps afterward so they inherit the updated PATH.'
        fi
    fi
    if [[ "$uv" != /* || ! -x "$uv" ]] || ! "$uv" --version; then
        printf '%s\n' 'uv is not usable on PATH. Open a new terminal, check uv --version, then retry.' >&2; exit 1
    fi
    printf '%s\n' 'Preparing Python 3.12 for setup; the first download may take a moment.'
    # Ensure the same managed interpreter is available for later offline removal.
    # Do not select a project's virtualenv or create Python shims on the user's PATH.
    "$uv" python install --no-config --no-bin 3.12
    local python
    python="$("$uv" python find --managed-python --system --no-project --no-config --offline --no-python-downloads 3.12)"
    [[ "$python" = /* && -x "$python" ]] || { printf '%s\n' 'No usable managed Python was found.' >&2; exit 1; }
    "$python" -I "$helper" ${args[@]+"${args[@]}"}
)

main "$@"
