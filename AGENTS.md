# python-django-api-template: agent guide

Stack: Python 3.12, Django 5.2 LTS, Django REST framework 3.18, simplejwt 5.5 (with the blacklist app), drf-yasg, django-filter, Celery 5.4 with Redis and django-celery-beat (database scheduler), Postgres 14. Tests use Django's test runner, not pytest. Trust `requirements/*.txt` over the README for versions.

## Agent shell rules
- Start agents from this repo's root, not from a parent folder or a subfolder. `.claude/settings.json` (permission rules and the guard hook) loads only from the folder the agent starts in.
- Agent shells do not stay activated. Call every tool by its venv path (`.venv/bin/python`, `.venv/bin/flake8`) and run commands from the repo root.
- Never read, print, copy or edit `.env` or `.env.<name>`. A human fills it in. If you need a value, ask. `.env.example` is safe to read and must list every variable.
- Search code with `git grep -n <pattern>` (add `--untracked` for files you just created): it never reads gitignored files such as `.env`. Don't use `grep -r` on the repo.
- Claude Code reads this file only if there is no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in this folder or any folder above it, committed or not. Don't create one. For personal notes use `~/.claude/CLAUDE.md`, or start a `CLAUDE.local.md` with the line `@AGENTS.md`.

## Setup (host)
- `uv venv --seed --python 3.12 --allow-existing .venv`. Use 3.12, as the Dockerfile and CI do: on 3.13+ psycopg2-binary 2.9.9 has no wheel and its source build fails. Use `.venv`, which the agent docs and allow rules assume; flake8 and isort skip `.venv`, `env` and `venv`.
- `.venv/bin/pip install -r requirements/dev.txt -r requirements/test.txt`. `dev.txt` alone has no faker, factory_boy or coverage, so the tests fail to import. Re-run it after changing requirements.
- A human runs `cp .env.example .env` and fills SECRET_KEY (required: every manage.py command raises ImproperlyConfigured without it) and DB_DEV_USER, DB_DEV_PASSWORD and DB_DEV_NAME. Compose builds POSTGRES_* from these, and the db volume keeps the values it was first created with. Keep DB_DEV_HOST=127.0.0.1 and the Redis URLs from `.env.example`: an empty value in `.env` overrides the default in settings, and an empty DB_DEV_HOST makes psycopg2 use the local Unix socket instead of the compose database.
- `docker compose up -d db redis` starts Postgres on 127.0.0.1:5432 and Redis on 127.0.0.1:6379. DB_DEV_HOST=127.0.0.1 and the localhost Redis URLs reach whatever listens there, so check the ports before any session that runs tests, migrate or Celery. On macOS: `lsof +c 0 -nP -iTCP:5432 -iTCP:6379 -sTCP:LISTEN`; before you start db and redis the output must be empty, and while they run the only rows may be `com.docker.backend` on 127.0.0.1. On Linux: `ss -ltn 'sport = :5432 or sport = :6379'`; before you start them any row is another server, and while they run any row other than 127.0.0.1:5432 and 127.0.0.1:6379 is. Any other listener (Postgres.app, a Homebrew or distro postgres, a native redis-server, another project's container) means the tests, which drop `test_<DB_DEV_NAME>`, would hit that server: stop and ask the human. Also stop if compose reports a port already in use.

## Commands
- Run: `.venv/bin/python manage.py runserver` (127.0.0.1:8000). If `lsof +c 0 -nP -iTCP:8000 -sTCP:LISTEN` (Linux: `ss -ltn 'sport = :8000'`) shows a listener, another server holds the port and requests to it reach that server: use `.venv/bin/python manage.py runserver 127.0.0.1:8001`. Send requests only after the log shows `Starting development server at`. The default settings module is `django_template.settings.dev` (manage.py, wsgi.py, asgi.py, celery.py).
- Test: `.venv/bin/python manage.py test --noinput [--keepdb]`. One test: `.venv/bin/python manage.py test --noinput authentication.tests.test_views.TestCalls.test_call_login`. Always pass `--noinput`: a test database left by `--keepdb` or an interrupted run otherwise triggers a yes/no prompt, which fails in an agent shell. Tests use Postgres from DB_DEV_* (settings/dev.py) and create `test_<DB_DEV_NAME>`, so the DB user needs CREATEDB. Redis is not needed.
- Coverage, as CI runs it: `.venv/bin/coverage run --source='.' manage.py test --noinput && .venv/bin/coverage report`
- Checks: `.venv/bin/python manage.py check` and `.venv/bin/python manage.py makemigrations --check --dry-run` (expect "No changes detected").
- Lint with the venv versions from requirements/base.txt (CI and .pre-commit-config.yaml use the same): `.venv/bin/flake8 .`, `.venv/bin/black --check .`, `.venv/bin/isort --check-only .`. The repo is clean under all three and CI fails on any finding, so run them before you finish. To fix formatting, run `.venv/bin/black` and `.venv/bin/isort` on the files you touched.
- Migrations: `.venv/bin/python manage.py makemigrations <app_label> --name <change>`, `sqlmigrate <app> <NNNN>`, `migrate`. Read `.claude/rules/migrations.md` before touching models or migrations.
- Celery worker with embedded beat, as docker compose runs it (Linux): `.venv/bin/celery -A django_template worker --beat --scheduler django -l info -E`. On a macOS host this fails silently: celery 5.4's embedded beat crashes and the prefork pool fails every task, yet the worker still logs `ready`. On macOS run two processes instead: `.venv/bin/celery -A django_template worker -P solo -l info -E` and `.venv/bin/celery -A django_template beat --scheduler django -l info`, and check the worker log shows `succeeded`, not just `ready`. Flower: `.venv/bin/celery -A django_template flower`.
- Docker dev: `docker compose up --build`. In `.env` that needs DB_DEV_HOST=db, BROKER_URL=redis://redis:6379/0 and CELERY_RESULT_BACKEND=redis://redis:6379/1. Real env vars override `.env` (load_dotenv never overwrites), so on the host run `DB_DEV_HOST=127.0.0.1 .venv/bin/python manage.py test --noinput`.
- Tests inside docker (the image has only dev requirements): `docker compose run --rm -T -e DB_DEV_HOST=db web sh -c 'pip install -r requirements/test.txt && python manage.py test --noinput'`. The `-e` is needed because the web service reads DB_DEV_HOST only from `.env`, where the host value 127.0.0.1 means the container itself.
- Prod stack (ask first): `docker compose -f docker-compose.prod.yml up --build -d`. Needs SECRET_KEY, ALLOWED_HOSTS, DB_* with DB_HOST=db, and REDIS_PASSWORD.
- Broken, do not use: `manage.py loaddata authentication/fixtures/customer.json` fails with "Customer has no field named user".
- Agent hook tests: `python3 -m unittest discover -s .claude/hooks` (CI runs them too).
- CI (`.github/workflows/tests.yml`) builds a throwaway `.env`, so it needs no repository secret. It runs lint and format checks, `check`, `makemigrations --check`, migrate, the tests with coverage, and the hook tests.

## Where migrations run
By hand, on every web container start in dev and prod (`docker-entrypoint.sh` runs `migrate` before the server starts: runserver in dev, gunicorn in prod), in CI, and when the test runner builds its database. The worker and flower never migrate. The worker embeds beat, so run exactly one worker replica.

## Layout
- `django_template/`: `settings/{base,dev,prod}.py`, `urls.py` (swagger, redoc, `api/v1/auth/`), `celery.py`, `wsgi.py`, `asgi.py`.
- `authentication/`: packages `models/`, `serializers/`, `views/`, `admin/`, `factories/`, `tests/`. One class per file: `models/<thing>.py`, elsewhere `<thing>_<kind>.py` (`serializers/register_serializer.py`, `views/register_view.py`, `admin/customer_admin.py`, `factories/customer_factory.py`). `models/`, `serializers/` and `views/` re-export from their package `__init__`; `admin/__init__.py` registers each ModelAdmin. Import factories from their module (`from authentication.factories.customer_factory import CustomerFactory`). Also `urls.py` and `tasks.py`.
- `django_core/`: `BaseModel` (abstract `created_at` and `updated_at`), plus empty placeholders (`permissions.py`, `mixins.py`, `exceptions.py`, `middleware.py`, `services/`, `utils/`) for cross-app code.
- `requirements/{base,dev,test,prod}.txt`, with exact `==` pins. Pin every new dependency.
- Skills for repeatable tasks are in `.agents/skills/` (Claude Code reaches them through the `.claude/skills/` symlinks). If `.claude/skills/<name>` is a one-line text file rather than a folder (a Windows clone without symlinks), read `.agents/skills/<name>/SKILL.md` directly and tell the user to run `git config core.symlinks true` and `git checkout -- .claude/skills`.

## Conventions
- Export new modules explicitly (`from .x_view import XView`, plus `__all__`). Don't add new `import *`. Keep `TokenRefreshSerializer` (named as a dotted path in `SIMPLE_JWT`) and `Customer` importable from their packages.
- Models subclass `django_core.models.BaseModel`. A new AppConfig sets `default_auto_field = "django.db.models.BigAutoField"`.
- Users are `auth.User` (there is no AUTH_USER_MODEL). `Customer` is a multi-table child of User (`user_ptr`, table `customer`). `/register` creates a plain User, so most users have no Customer row. Point foreign keys at `settings.AUTH_USER_MODEL`.
- DRF: generic class-based views. Mount each app with `path("api/v1/<app>/", include(...))` and name every route. There is no default pagination, so set `pagination_class`. Add `@swagger_auto_schema` to custom APIViews and check that `/swagger.json` still renders.
- Settings: new values use `os.getenv("X", <non-secret default>)`, and booleans use `env_bool()`. Secrets get no default. Add every new variable to `.env.example`. Prod settings (`settings/prod.py`) need `requirements/prod.txt`.
- Celery: `@shared_task(name="<app>.<task>")`. Never create a `Celery()` app in `tasks.py`. Settings take the `CELERY_` prefix: `CELERYBEAT_SCHEDULE` is ignored, use `CELERY_BEAT_SCHEDULE`. Beat crontabs run in Asia/Ho_Chi_Minh while TIME_ZONE is UTC.

## Traps already in the code (don't copy them)
- No DEFAULT_PERMISSION_CLASSES is set, so DRF defaults to AllowAny.
- `RegisterSerializer.create` saves the raw password with `objects.create(**validated_data)` before hashing it.
- `authentication/tasks.py` creates its own `Celery("tasks")` app with no broker, and the `CELERYBEAT_SCHEDULE` in `settings/base.py` is ignored.
- `CustomerFactory` evaluates Faker once at class level, so a second instance collides, and it stores the password unhashed.

## Security rules
- Every view sets `permission_classes`, and querysets are scoped to `request.user`.
- Hash passwords with `create_user()` or `set_password()` before the first save. Never `objects.create(password=...)`. Password fields are `write_only` and use `validate_password`.
- User serializers list explicit fields, never `"__all__"`. Staff, superuser and permission fields are read-only.
- Secrets come only from the environment, with no real defaults. Never run `manage.py diffsettings` or `docker compose config`: both print secrets.
- Never add destructive steps to `docker-entrypoint.sh` (it used to flush the database on every start). Never run `flush`, `migrate <app> zero` or `docker compose down -v`.
- Prod compose publishes no db or redis ports, and Sentry never sets `send_default_pii=True`.

## Before finishing
Run the affected app's tests, `makemigrations --check --dry-run`, and the linters on the files you touched. Update `.env.example` and the README when commands or variables change. Fill in `.github/pull_request_template.md` (there is no CHANGELOG).

## Code Review Rules
Flag: views without `permission_classes`; unhashed password writes; `"__all__"` on a user serializer; edited or backward-incompatible migrations; RunPython without a reverse; a new `Celery()` app or `CELERYBEAT_*` names; secrets with defaults; db or redis ports published in prod compose; new endpoints without tests for 401 and the happy path.
