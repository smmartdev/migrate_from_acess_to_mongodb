# Access to MongoDB Migrator

A Python tool that automatically migrates **all tables** from a Microsoft Access database (`.accdb` / `.mdb`) into MongoDB — no manual mapping, no table names to configure. Point it at your Access file and a MongoDB database name, and it discovers and copies everything.

Built for large databases (tested on 4M+ records) with batched reads, bulk writes, a progress bar, and crash-safe resume.

## Features

- **Zero configuration** — automatically discovers every table, every column, and (when the ODBC driver supports it) the primary key.
- **1:1 mapping** — each Access table becomes a MongoDB collection with the same name; each column becomes a field with the same name.
- **Handles large tables** — reads with `fetchmany()` in configurable batches (never loads a whole table into memory), writes with `bulk_write(ordered=False)`.
- **Resume after a crash** — progress is saved after every batch to `resume.json`. If the process is killed (power loss, Ctrl+C, error), just run it again and it continues from where it stopped.
- **Safe by default** — a normal re-run never re-drops or duplicates already-imported data. Full rebuild only happens with `--fresh`.
- **BSON-safe type conversion** — Access `Decimal` fields are automatically converted to `int`/`float` (BSON doesn't support raw `decimal.Decimal`).
- **Automatic indexing** — when a table's primary key is detected, a unique index is created on it after import.
- **Logging** — every run writes to `logs/import.log` (progress) and `logs/errors.log` (errors only).

## Requirements

- Python 3.9+
- Windows (or any OS with a working Access ODBC driver)
- **Microsoft Access Database Engine** (ODBC driver) installed — download the "Microsoft Access Database Engine Redistributable" from Microsoft if `pyodbc.connect()` fails to find the driver
- A running MongoDB instance

## Installation

```bash
git clone https://github.com/smmartdev/migrate_from_acess_to_mongodb
cd migration
pip install -r requirements.txt
```

## Usage

```bash
python migrate.py --access-file "C:\path\to\database.accdb" --mongo-db my_database
```

Force a full rebuild (drops all target collections first):

```bash
python migrate.py --access-file "C:\path\to\database.accdb" --mongo-db my_database --fresh
```

Custom MongoDB connection string:

```bash
python migrate.py --access-file "C:\path\to\database.accdb" --mongo-db my_database --mongo-uri "mongodb://user:pass@host:27017"
```

### CLI options

| Option | Required | Default | Description |
|---|---|---|---|
| `--access-file` | Yes* | `ACCESS_DB_PATH` env var | Full path to the `.accdb`/`.mdb` file |
| `--mongo-db` | Yes* | `MONGO_DB_NAME` env var | Target MongoDB database name |
| `--mongo-uri` | No | `mongodb://localhost:27017` | MongoDB connection string |
| `--fresh` | No | off | Drop all collections and re-import everything from scratch |

*Can also be set via environment variables instead of flags: `ACCESS_DB_PATH`, `MONGO_URI`, `MONGO_DB_NAME`.

### Batch size

Default batch size is 20,000 records (read from Access and written to MongoDB per round-trip). Override it:

```bash
set BATCH_SIZE=50000
python migrate.py --access-file "..." --mongo-db my_database
```

## How resume works

Progress is saved to `migration/resume.json` after every successful batch, per table:

```json
{
  "tables": {
    "Sgaza":        { "offset": 2400000, "done": false },
    "Governorates": { "offset": 17,      "done": true }
  }
}
```

- If the process stops for any reason, just re-run `python migrate.py ...` (same command, **without** `--fresh`) — it will skip finished tables and resume the unfinished one from its last saved offset.
- `--fresh` deletes `resume.json` and all target collections, then starts over.
- Delete `resume.json` manually if you ever want to force a "fresh" state without using `--fresh`.

## Notes and limitations

- **Field names and values are copied as-is.** No renaming, no translation of coded values (e.g. a numeric gender code stays a number). If you need custom transformations for specific fields, add them on top of `importer.py`'s `clean_value()` function.
- **Primary key detection depends on the ODBC driver.** Some Access driver builds (notably older/32-bit ones) don't support `SQLPrimaryKeys` and will raise `IM001`. The tool catches this automatically and treats the table as having no known primary key — it will still import fine, but:
  - no unique index will be created on that table, and
  - resuming a crash *in the middle* of that specific table is not 100% order-guaranteed (Access has no default row order without `ORDER BY`).
- **System tables are skipped automatically** (anything starting with `MSys`).
- **Empty strings and whitespace-only strings** in Access are converted to `null` in MongoDB.

## Troubleshooting

**`cannot encode object: Decimal(...), of type: <class 'decimal.Decimal'>`**
Already handled — `clean_value()` converts `Decimal` to `int`/`float` before insert. If you still see this, check `logs/errors.log` for the exact field/table and open an issue.

**`[IM001] ... Driver does not support this function (0) (SQLPrimaryKeys)`**
Expected with some Access ODBC drivers — see [Notes and limitations](#notes-and-limitations) above. The migration still completes normally.

**Collection ends up empty despite a "success" log line**
Check `logs/errors.log` first — every insert failure is logged there with the exact exception. The final summary line always reports both the number of records *read* and the number *actually inserted*, plus the real live count in MongoDB, so a mismatch is easy to spot.

**Can't connect to Access**
Make sure you're running a Python interpreter with the same bitness (32-bit/64-bit) as your installed Access ODBC driver.

## License

MIT — use it, fork it, adapt it.