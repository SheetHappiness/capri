"""Local milestone launcher. Credentials are never accepted in CLI arguments."""
import argparse
import asyncio
import logging
from pathlib import Path
from .app import run
from .guest_probe import run_guest_probe


def main():
    parser = argparse.ArgumentParser(description='Capri first owner-DM milestone')
    parser.add_argument('--data', type=Path, default=Path('.runtime'))
    parser.add_argument('--omp', type=Path, help='Override the bootstrapped <data>/bin/omp.exe')
    parser.add_argument('--guest-probe', choices=['answer', 'edit'], help='Telegram-only transport test; pauses DM service')
    args = parser.parse_args()
    data = args.data.resolve()
    executable = args.omp.resolve() if args.omp else data / 'bin/omp.exe'
    if not args.guest_probe and not executable.is_file():
        parser.error(f'Missing OMP runtime: {executable}. Run ./scripts/bootstrap.ps1 -Data "{data}"')
    token_path = args.data / 'bot-token'
    if not token_path.exists():
        parser.error('Place the Telegram token in the private data directory as bot-token')
    token = token_path.read_text(encoding='utf-8').strip()
    try:
        if args.guest_probe:
            logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
            asyncio.run(run_guest_probe(token, args.data.resolve(), phase=args.guest_probe))
        else:
            asyncio.run(run(token, executable, data))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
