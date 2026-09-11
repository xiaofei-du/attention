#!/usr/bin/env python3
"""Run with .venv/bin/python after uv sync; stdout is exclusively MCP traffic."""

import argparse
import asyncio
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path(__file__).resolve().parent / '.state')
    parser.add_argument('--summary-socket', type=Path)
    parser.add_argument('--provider', choices=['codex', 'claude-code'], default='codex')
    parser.add_argument('--confirm-controls', action='store_true', help='Require native confirmation for every setting mutation')
    args = parser.parse_args()
    from nkc.mcp_server import serve
    asyncio.run(serve(args.state_dir.resolve(), confirm_controls=args.confirm_controls,
                      summary_socket=args.summary_socket, provider=args.provider))


if __name__ == '__main__':
    main()
