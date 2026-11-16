"""Inspect immutable MEP evidence or append explicit engineering review events."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'etl-pipeline' / 'scripts'))
from mep_store import Store, write_json


def _open_existing(db):
    if not Path(db).is_file():
        raise ValueError('Evidence database does not exist; ingest through etl-pipeline first')
    return Store(db)


def trace(db, record_id):
    store = _open_existing(db)
    try:
        return store.inspect(record_id)
    finally:
        store.close()


def add_review(db, record_id, reviewer, decision, reason, field=None, value=None):
    store = _open_existing(db)
    try:
        return store.review(record_id, reviewer, decision, reason, field, value)
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='Source locator, archive hash and complete review history')
    review = sub.add_parser('review', help='Append a review decision; preserve the raw observation')
    for child in (inspect, review):
        child.add_argument('--db', required=True)
        child.add_argument('--record', required=True)
        child.add_argument('--output')
    review.add_argument('--reviewer', required=True)
    review.add_argument('--decision', choices=['approved', 'rejected', 'needs_review'], required=True)
    review.add_argument('--reason', required=True)
    review.add_argument('--field', help='Engineering interpretation field; never rewrites evidence')
    review.add_argument('--value-json', help='JSON value including quotes for text; null clears an interpretation')
    args = parser.parse_args(argv)
    if args.output and Path(args.output).exists():
        raise ValueError('Output already exists; refusing overwrite')
    if args.command == 'inspect':
        result = trace(args.db, args.record)
    else:
        if args.field is None and args.value_json is not None:
            raise ValueError('--value-json requires --field')
        value = json.loads(args.value_json) if args.value_json is not None else None
        result = add_review(args.db, args.record, args.reviewer, args.decision, args.reason, args.field, value)
    write_json(result, args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as error:
        raise SystemExit(str(error))
