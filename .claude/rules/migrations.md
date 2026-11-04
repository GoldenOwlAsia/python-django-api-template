---
paths:
  - "**/migrations/*.py"
  - "**/models/*.py"
  - "**/models.py"
---
# Migration rules

- Generate migrations, don't hand-write them: `.venv/bin/python manage.py makemigrations <app> --name <change>`. Always pass an app label. Then run `.venv/bin/black` on the new file: Django formats it only when `black` is on PATH, and the venv isn't activated.
- Never edit or delete a migration that is already on the main branch. Add a new one. Don't squash without asking.
- The web container runs `migrate` on every start (docker-entrypoint.sh) while the worker still runs the old code. Expand, deploy, then contract: new columns are nullable or have a default, and renames and drops wait for the next release.
- NOT NULL on `customer` or `auth_user` needs a default, or three steps: add it nullable, backfill, then set NOT NULL.
- Data migrations use `apps.get_model(...)`, never imports of app models. Always `RunPython(forward, reverse)`, batched with `.iterator(chunk_size=1000)`.
- Indexes on large tables: `AddIndexConcurrently` (django.contrib.postgres.operations) in a migration with `atomic = False`.
- Never add fields to `auth.User` and don't set AUTH_USER_MODEL. Foreign keys use `settings.AUTH_USER_MODEL`. `Customer` is a multi-table child of User keyed on `user_ptr_id`, and most users have no Customer row.
- Verify with `.venv/bin/python manage.py sqlmigrate <app> <NNNN>`, `.venv/bin/python manage.py makemigrations --check --dry-run`, then `.venv/bin/python manage.py test --noinput <app>`.
