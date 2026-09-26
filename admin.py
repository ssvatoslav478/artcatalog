import argparse
from pathlib import Path
from catalog import load_catalog

BASE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Управление каталогом рисунков')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Проверить каталог и локальные рисунки')
    args = parser.parse_args()
    if args.command == 'check':
        print(f'Карточек: {len(load_catalog(BASE / "participants.json"))}')
        return


if __name__ == '__main__':
    main()
