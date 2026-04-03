# Database Migration Guide

## 1) Apply Pending Migrations

```bash
./.venv/bin/python -m backend.database.runtime.migration_cli apply
```

## 2) Check Migration History

```bash
./.venv/bin/python -m backend.database.runtime.migration_cli status --limit 50
```

`schema_migrations` stores:

- `version`, `filename`, `checksum`
- `status` (`applied` / `failed` / `rolled_back`)
- execution timing and statement count
- rollback file and rollback status/error

## 3) Rollback Strategy

Rollback requires a matching `*.down.sql` file:

- same directory: `sql/migrations/007_xxx.down.sql`
- or rollback directory: `sql/migrations/rollback/007_xxx.down.sql`

Dry run:

```bash
./.venv/bin/python -m backend.database.runtime.migration_cli rollback --steps 1 --dry-run
```

Rollback latest one:

```bash
./.venv/bin/python -m backend.database.runtime.migration_cli rollback --steps 1
```

Rollback specific version:

```bash
./.venv/bin/python -m backend.database.runtime.migration_cli rollback --version 007
```

If rollback SQL is missing, migration manager marks rollback state and stops with an explicit error.
