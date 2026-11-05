#!/usr/bin/env python3
"""Read a directory of cards with their ledgers: read_cards.py DIR [DIR ...]

For every card in DIR/cards (or in DIR itself) with its ledger in DIR/ledgers, this reads the card
the way the kit reads it: it binds every record to the value and passage it was given for. The
sources are not fetched, so the passages of `src` are not re-read; what is checked here is that the
kit can read the card at all, and that its records still bind.

A card the kit cannot read is the failure this script exists for: when a rule of the kit changes, a
card the kit has already produced must not become unreadable. Exit 0 only when every card is read
with no error. Records read under an earlier rendering of their value are printed as NOTE, not as a
failure, and are resolved again at that card's next rebuild (references/resolution.md).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ledger  # noqa: E402


def cards_and_ledgers(root):
    """(card path, ledger path or None) for every card under root."""
    root = Path(root)
    cards = sorted((root / 'cards').glob('*.json')) if (root / 'cards').is_dir() else sorted(root.glob('*.json'))
    for card in cards:
        for led in (root / 'ledgers' / card.name, card.with_suffix('.ledger.json'),
                    card.parent / f'{card.stem}-entailment-ledger.json'):
            if led.exists():
                yield card, led
                break
        else:
            yield card, None


def read(card_path, ledger_path):
    """(errors, legacy keys) of one card, or a one-item error list when it cannot be read."""
    card = json.loads(Path(card_path).read_text())
    ledger = json.loads(Path(ledger_path).read_text()) if ledger_path else None
    legacy = []
    try:
        return check_ledger.check(card, ledger, None, legacy), legacy
    except Exception as e:  # noqa: BLE001  the point of this script is that this must not happen
        return [f'the kit cannot read this card: {type(e).__name__}: {e}'], legacy


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(2)
    read_count, failed = 0, 0
    for root in sys.argv[1:]:
        for card_path, ledger_path in cards_and_ledgers(root):
            errors, legacy = read(card_path, ledger_path)
            read_count += 1
            name = Path(card_path).name
            if ledger_path is None:
                print(f'{name}: no ledger beside it (expected DIR/ledgers/{name})')
            for key in sorted(set(legacy)):
                print(f'NOTE {name}: {key}: record read under the rendering in force when it was checked; '
                      'it is resolved again at the next rebuild')
            for e in errors:
                print(f'FAIL {name}: {e}')
            failed += bool(errors)
            if not errors:
                print(f'{name}: read')
    print(f'CARDS READ {read_count - failed}/{read_count}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
