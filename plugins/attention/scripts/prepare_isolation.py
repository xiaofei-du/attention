#!/usr/bin/env python3
"""Write a new, reviewable isolation bundle. Does not apply settings or start hosts."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nkc.isolation import prepare_isolation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'runtime', 'state', 'socket', 'output', 'python'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--deny-credential', action='append', type=Path, default=[],
                        help='Additional absolute private credential path (repeatable)')
    parser.add_argument('--runtime-read-root', action='append', type=Path, default=[],
                        help='Additional protected interpreter/dependency installation root (repeatable)')
    args = parser.parse_args()
    # Deny ordinary user credential stores explicitly in both hosts. Minimal
    # Codex reads additionally deny unlisted home paths; Claude does not.
    home = Path.home()
    credentials = [home/name for name in ('.ssh', '.aws', '.config/gcloud', '.azure',
        '.kube', '.docker', '.codex', '.claude', '.claude.json', '.npmrc', '.netrc',
        '.git-credentials', 'Library/Keychains')]
    try:
        output = prepare_isolation(project=args.project, runtime=args.runtime, state=args.state,
            socket_path=args.socket, output=args.output, python=args.python,
            credential_paths=[*credentials, *args.deny_credential], runtime_read_paths=args.runtime_read_root)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Isolation files were not prepared: {exc}\n')
    print(output)


if __name__ == '__main__': main()
