#!/usr/bin/env python3
"""PreToolUse hook: stop shell commands that destroy local data or expose secrets.

Claude Code sends each Bash or Monitor call as JSON on stdin. This script exits
2 to block the command (stderr goes back to Claude), prints an "ask" decision to
make Claude Code prompt the user, or exits 0 and leaves the decision to the
normal permission rules. Repo-specific rules and fixture cases live in
../guard.json.

It uses only the standard library, because hooks run with the system python3
rather than the project venv. It fails open: on an internal error it exits 0,
and the deny rules in .claude/settings.json still cover the critical cases.
After any change, run: python3 -m unittest discover -s .claude/hooks

The Django, FastAPI and Flask templates use the same file. Keep them identical.
"""

import ast
import fnmatch
import glob
import io
import itertools
import json
import os
import re
import shlex
import sys
import tokenize
import warnings
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "guard.json"

# Rules match one simple command at a time, written from the program name on,
# with tokens joined by single spaces. Whitespace inside a quoted argument is
# shown as "·", so text inside a commit message can't match a rule.
COMMON_BLOCK = [
    {
        "pattern": r"(^|\s|/)docker(\s+compose|-compose)\s(.*\s)?down(\s.*)?\s"
        r"(-[a-zA-Z]*v[a-zA-Z]*|--volumes)(=\S*)?(\s|$)",
        "reason": "`down -v` deletes the database volume. "
        "Use `docker compose down` without -v.",
    },
    {
        "pattern": r"(^|\s|/)docker(\s+compose|-compose)(\s+-\S+(\s+[^-\s]\S*)?)*"
        r"\s+(config|convert)(\s|$)",
        "unless": r"\s(config|convert)(\s(?!-o\s|--output\s)\S+)*"
        r"\s(--(services|volumes|profiles|images|quiet)|-q)(\s|$)",
        "reason": "`docker compose config` prints the secrets it interpolates "
        "from .env. Use --services or --quiet, or read the compose file.",
    },
    {
        "pattern": r"(^|\s|/)docker\s+(volume\s+(rm|prune)|system\s+prune"
        r"|container\s+prune)(\s|$)",
        "reason": "this deletes Docker volumes or stopped containers that hold "
        "local databases.",
    },
    {
        "pattern": r"^(\S*/)?(dropdb|dropuser)(\s|$)",
        "reason": "this drops a Postgres database or role.",
    },
    {
        "pattern": r"^(\S*/)?git\s(.*\s)?push(\s.*)?\s"
        r"(--force|-[a-zA-Z]*f[a-zA-Z]*|\+\S+)(\s|$)",
        "reason": "a force push rewrites shared history. Ask the user; "
        "prefer --force-with-lease.",
    },
    {
        "pattern": r"^(\S*/)?git\s(.*\s)?clean(\s.*)?\s-[a-zA-Z]*[xX][a-zA-Z]*(\s|$)",
        "reason": "`git clean -x` deletes ignored files, including .env and other "
        "config a human filled in.",
    },
    {
        "pattern": r"(^|\s|/)alembic\s(.*\s)?downgrade\s+base(\s|$)",
        "unless": r"\s--sql(\s|$)",
        "reason": "`alembic downgrade base` drops every table. "
        "Downgrade one revision at a time, and ask first.",
    },
    {
        "pattern": r"(^|\s|/)dotenv(\s+-\S+(\s+[^-\s]\S*)?)*"
        r"\s+(list|get|set|unset|run)(\s|$)",
        "unless": r"\s(-f|--file)(\s+|=)\S*\.env\.(example|sample|template)(\s|$)",
        "reason": "the dotenv CLI prints or rewrites .env, and `dotenv run` "
        "loads its values.",
    },
]
COMMON_ASK = [
    {
        "pattern": r"(^|\s|/)docker\s+(container\s+)?inspect(\s|$)",
        # Only a template of plain field paths skips the prompt: not json, $,
        # index, {{.}}, .Config or .Config.Env, and no later -f/--format.
        "unless": r"\s(-f|--format)(\s|=)(?=\S*\{\{)(\{\{·*(((range|with)·+)?"
        r"(json·+)?\.(Config\.(?!Env\b)\w+|(?!Config\b)[A-Z]\w*)(\.\w+)*|end)"
        r"·*\}\}|[^{}\s])+(?=\s|$)(?!.*\s(-[a-zA-Z]*f|--format))",
        "reason": "`docker inspect` prints the container environment, which holds "
        "SECRET_KEY and the database passwords from .env. Use --format with the "
        "fields you need, such as '{{.State.Health.Status}}'.",
    },
    {
        "pattern": r"(^|\s|/)alembic\s(.*\s)?stamp(\s|$)",
        "unless": r"\s--sql(\s|$)",
        "reason": "`alembic stamp` changes the recorded schema version without "
        "running any migration.",
    },
]

# Files that are always secret: .env and .env.<name> but not the committed
# .env.example, and a process environment. guard.json can add more.
COMMON_SECRET_PATHS = [
    r"(^|/)\.env(?!\.(example|sample|template)$)(\.[\w.-]+)?$",
    r"^/proc/[^/]+/environ$",
]

# fmt: off
# Programs that print, copy, send, overwrite or delete the files they are given.
READERS = {
    "cat", "tac", "less", "more", "head", "tail", "nl", "strings", "od", "xxd",
    "hexdump", "base64", "bat", "view", "vi", "vim", "nvim", "nano", "emacs",
    "code", "open", "grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk",
    "gawk", "cut", "sort", "uniq", "diff", "cmp", "comm", "paste", "jq", "yq",
    "source", ".", "cp", "mv", "rsync", "scp", "tee", "dd", "tar", "zip",
    "curl", "wget", "nc", "rm", "unlink", "shred", "truncate", "ln", "install",
}
# For these, the first argument is a pattern or script, not a file.
PATTERN_FIRST = {
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk", "gawk", "jq", "yq",
}
PATTERN_OPTIONS = ("-e", "-f", "--regexp", "--file", "--expression")
PATTERN_OPTION_PREFIXES = ("--regexp=", "--file=", "--expression=")
INLINE_PATTERN_OPTIONS = ("-e", "--regexp", "--expression")
EXCLUDE_OPTIONS = ("--exclude", "--exclude-dir", "--exclude-from")
COPIERS = {"cp", "mv", "rsync", "scp", "install", "ln"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SQL_CLIENTS = {"psql", "pgcli", "mysql", "sqlite3"}
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
GROUP_ENDS = {"}", "done", "fi", "esac"}
# -exec programs that only list or count the files they are given.
FIND_HARMLESS = {"ls", "stat", "file", "wc", "du", "echo", "printf", "test", "["}
# Words that come before the real program in a simple command.
PREFIX_WORDS = {
    "!", "{", "}", "if", "then", "do", "else", "elif", "while", "until", "time",
    "exec", "command", "builtin", "nohup", "sudo", "doas", "env", "nice",
    "timeout", "xargs", "stdbuf", "caffeinate", "watch",
}
# `uv run python ...`, `poetry run python ...` and the like run the program after
# them. These options of theirs take a value.
RUNNERS = {"uv", "uvx", "poetry", "pipenv", "pdm", "hatch", "rye", "pixi"}
RUNNER_VALUE_OPTIONS = {
    "-w", "--with", "--with-editable", "--with-requirements", "-p", "--python",
    "--project", "--directory", "--config-file", "--cache-dir", "--env-file",
    "--extra", "--no-extra", "--group", "--no-group", "--only-group",
    "--package", "--from", "--index", "--default-index", "-i", "--index-url",
    "--extra-index-url", "-f", "--find-links", "--index-strategy",
    "--keyring-provider", "-P", "--upgrade-package", "--resolution",
    "--prerelease", "--exclude-newer", "--link-mode", "-C", "--config-setting",
    "--python-platform", "--color", "--allow-insecure-host", "-e",
    "--environment", "--manifest-path",
}
# Options of docker, docker compose, and docker exec/run that take a value.
DOCKER_GLOBAL_VALUE_OPTIONS = {
    "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file",
    "--profile", "-c", "--context", "-H", "--host", "--config", "-l",
    "--log-level", "--ansi", "--progress",
}
DOCKER_VALUE_OPTIONS = {
    "-e", "--env", "--env-file", "-u", "--user", "-w", "--workdir", "--name",
    "-v", "--volume", "-p", "--publish", "--entrypoint", "-l", "--label",
    "--network",
}
# fmt: on

INTERPRETER = re.compile(r"(python[\d.]*|perl|ruby|node|php|deno|bun)$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A heredoc delimiter word, with any parts quoted by ', " or \. A digit right
# after << (as in 1<<2) is a shift, not a heredoc.
HEREDOC = re.compile(
    r"(?<!<)<<(-?)[ \t]*((?=[A-Za-z_'\"\\])"
    r"(?:'[^'\n]*'|\"[^\"\n]*\"|\\.|[^\s;&|<>()'\"\\])+)"
)
UNQUOTE = re.compile(r"'([^']*)'|\"([^\"]*)\"|\\(.)")
# $(...), `...` and the process substitutions <(...) and >(...). A heredoc
# body expands only the first two.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`|[<>]\(([^()]*)\)")
BODY_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
DESTRUCTIVE_SQL = re.compile(
    r"\b(drop\s+(table|database|schema|owned|role|user)|truncate)\b", re.I
)
SQL_SHELL = re.compile(r"(^|\s|/)(dbshell|psql|pgcli)(\s|$)")
CLIENT_WORD = re.compile(r"(^|\s|/)(dbshell|psql|pgcli|mysql|sqlite3|redis-cli)(\s|$)")
# Arguments that make a database client read statements from somewhere other
# than its own arguments: a variable, a redirect, a file or a meta-command.
READS_ELSEWHERE = re.compile(
    r"\$|^<$|^-[a-zA-Z]*f|^--file(=|$)|(^|\s)(\\i\w*|\.read|source)(\s|$)"
)
REDIS_FLUSH = re.compile(r"\bflush(all|db)\b", re.I)
DOTENV_CALL = re.compile(r"\b(dotenv_values|load_dotenv|find_dotenv)\s*\(")
SAFE_ENV_FILE = re.compile(r"\.env\.(example|sample|template)\b")
SECRET_NAME = re.compile(
    r"SECRET|PASSW|TOKEN|KEY|DSN|DATABASE_URL|BROKER_URL|_BACKEND$|_URI$", re.I
)
SECRET_VAR = re.compile(
    r"\$\{?[A-Za-z0-9_]*(SECRET|PASSW|TOKEN|KEY|DSN|DATABASE_URL|BROKER_URL"
    r"|_BACKEND|_URI)",
    re.I,
)
CODE_WORD = re.compile(r"[\w./@-]+")
STRING_LITERAL = re.compile(r"(['\"`])(.*?)\1", re.S)
IMPORT = re.compile(
    r"(?:^|[;:])\s*(?:from\s+([\w.]+)\s+import"
    r"|import\s+([\w.]+(?:\s*,\s*[\w.]+)*))",
    re.M,
)
PUNCTUATION = "();<>|&\n"
QUOTED_PUNCTUATION = {
    c: chr(0xE000 + i) for i, c in enumerate(PUNCTUATION) if c != "\n"
}
RESTORE_PUNCTUATION = {ord(v): k for k, v in QUOTED_PUNCTUATION.items()}
NEUTRALIZE_PLACEHOLDERS = {ord(v): "\ufffd" for v in QUOTED_PUNCTUATION.values()}
CONTAINER_ENV_REASON = (
    "the container environment holds SECRET_KEY and the database and Redis "
    "passwords from .env. Print only the non-secret variable you need: "
    "`printenv <NAME>`."
)


class Guard:
    def __init__(self, config, cwd):
        self.cwd = Path(cwd)
        self.block_rules = compile_rules(COMMON_BLOCK + config.get("block", []))
        self.ask_rules = compile_rules(COMMON_ASK + config.get("ask", []))
        self.secret_paths = [
            re.compile(p) for p in COMMON_SECRET_PATHS + config.get("secret_paths", [])
        ]
        self.env_rules = [
            (rule["name"], re.compile(rule["allow"]), rule["reason"])
            for rule in config.get("env", [])
        ]
        self.blocked = []
        self.asked = []

    def decide(self, command):
        self.check_command(command)
        if self.blocked:
            return "block", unique(self.blocked)
        if self.asked:
            return "ask", unique(self.asked)
        return "allow", []

    def check_command(self, command, depth=0):
        if depth > 6:
            return
        # Statements for a database client can come from anywhere in the
        # command line, heredoc bodies included (they may write a .sql file).
        full_text = command
        command, heredocs = strip_heredocs(command)
        for segment, quoted, body in heredocs:
            self.check_heredoc(segment, quoted, body, depth)
        command = self.check_substitutions(command, depth)
        earlier = [body for _, _, body in heredocs]
        printed = []
        for pipeline in split_pipelines(command.replace("`", " ")):
            for i, tokens in enumerate(pipeline):
                # A client that reads a pipe gets what the commands before it
                # printed, loops and groups included.
                text = " ".join(tokens)
                reads_pipe = i and CLIENT_WORD.search(text)
                sql_text = " ".join(earlier + [text]) if reads_pipe else text
                self.check_simple_command(tokens, sql_text, depth, full_text)
                if i:
                    # `echo '...' | python manage.py shell` runs the echoed code.
                    words = command_words(tokens)[1]
                    self.check_code_rules(words, " ".join(earlier))
                    # A program that runs code from stdin gets what echo and
                    # printf print before it, as it would get a heredoc:
                    # `echo "open('.env')" | python3`, `echo 'cat .env' | sh`.
                    # After a ( ) group or loop, all of them so far.
                    if runs_stdin(words):
                        group = not pipeline[0] or pipeline[0][0] in GROUP_ENDS
                        source = printed if group else printed[len(printed) - i :]
                        self.check_input(words, "\n".join(source), depth)
                earlier.append(text)
                printed.append(printed_text(tokens))

    def check_substitutions(self, command, depth, heredoc=False):
        """Check each $(...), `...`, <(...) and >(...) as its own command.

        Innermost first. Returns the command with each one replaced, so the
        surrounding command still parses. Single-quoted text is literal, except
        in a heredoc body, where quotes are ordinary characters.
        """
        pattern = BODY_SUBSTITUTION if heredoc else SUBSTITUTION
        for _ in range(10):
            blanked = blank_single_quoted(command, heredoc)
            matches = list(pattern.finditer(blanked))
            if not matches:
                break
            for match in reversed(matches):
                group = next(g for g in (1, 2, 3) if match.group(g) is not None)
                inner = command[match.start(group) : match.end(group)]
                self.check_command(inner, depth + 1)
                # <(...) stays in the outer command as one quoted word, so
                # `psql -f <(echo "DROP ...")` still shows psql the SQL.
                word = f" {shlex.quote(inner)} " if group == 3 else "$SUBST"
                command = command[: match.start()] + word + command[match.end() :]
        return command

    def check_heredoc(self, segment, quoted, body, depth):
        """Check a heredoc body that the shell expands or a program runs."""
        if not quoted:
            self.check_substitutions(body, depth, heredoc=True)
        # segment is the pipeline that reads the heredoc, so `cat <<EOF | python3`
        # counts as well as `python3 - <<EOF`.
        for pipeline in split_pipelines(segment.replace("`", " ")):
            for tokens in pipeline:
                self.check_input(command_words(tokens)[1], body, depth)

    def check_input(self, words, text, depth):
        """Check text that words read on stdin: code, a script or SQL."""
        in_container = bool(words) and os.path.basename(words[0]) in (
            "docker",
            "docker-compose",
        )
        if in_container:
            words = command_words(docker_inner_command(words[1:]))[1]
        if not words:
            return
        program = os.path.basename(words[0])
        if program in SHELLS:
            self.check_command(text, depth + 1)
            if in_container:
                self.check_container_script(text, depth + 1)
        elif INTERPRETER.match(program):
            python = program.startswith("python")
            self.check_code(text, python)
            parts = python_parts(text) if python else None
            self.check_code_rules(words, parts[0] if parts else text)
        if program in SQL_CLIENTS or SQL_SHELL.search(" ".join(words)):
            if DESTRUCTIVE_SQL.search(text):
                self.block_sql()
        if program == "redis-cli" and REDIS_FLUSH.search(text):
            self.block_redis()

    def check_code_rules(self, words, code):
        """Apply the repo rules to code an interpreter reads, as if given with -c.

        So `manage.py shell <<EOF` meets the same rule as `manage.py shell -c`.
        """
        if not words or not code or not INTERPRETER.match(os.path.basename(words[0])):
            return
        as_option = " ".join(words) + " -c " + re.sub(r"\s", "·", code)
        for rule in self.block_rules:
            if rule_matches(rule, as_option):
                self.blocked.append(rule["reason"])

    def check_simple_command(self, tokens, sql_text, depth, full_text=""):
        assignments, words = command_words(tokens)
        # A redirection may come before the program: `< .env cat`, `2>/dev/null ls`.
        while words:
            fd = 1 if len(words) >= 3 and words[0].isdigit() else 0
            if len(words) < fd + 2 or not is_redirect(words[fd]):
                break
            if self.is_secret(words[fd + 1]):
                self.block_secret(words[fd + 1])
            more, words = command_words(words[fd + 2 :])
            assignments += more
        declarers = ("export", "declare", "typeset", "local", "readonly")
        if words and words[0] in declarers:
            assignments += [w for w in words[1:] if ASSIGNMENT.match(w)]
        for assignment in assignments:
            self.check_assignment(assignment)
        if not words:
            return
        program = os.path.basename(words[0])
        text = " ".join(re.sub(r"\s", "·", w) for w in words)

        for rule in self.block_rules:
            if rule_matches(rule, text):
                self.blocked.append(rule["reason"])
        for rule in self.ask_rules:
            if rule_matches(rule, text):
                self.asked.append(rule["reason"])

        client = program in SQL_CLIENTS or SQL_SHELL.search(text)
        if (client or program == "redis-cli") and any(
            READS_ELSEWHERE.search(w) for w in words[1:]
        ):
            sql_text = full_text or sql_text
        if client and DESTRUCTIVE_SQL.search(sql_text):
            self.block_sql()
        if program == "redis-cli" and REDIS_FLUSH.search(sql_text):
            self.block_redis()

        if program == "find":
            self.check_find(words, depth)
        self.check_secret_files(program, words[1:])
        for i, word in enumerate(words[1:-1], start=1):
            if word == "<<<":
                self.check_input(words[:i], words[i + 1], depth)

        if program in SHELLS:
            for i, word in enumerate(words[1:-1], start=1):
                if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", word):
                    self.check_command(words[i + 1], depth + 1)
                    break
        elif program == "eval":
            self.check_command(" ".join(words[1:]), depth + 1)
        elif program in ("docker", "docker-compose"):
            sub, rest = docker_subcommand(words[1:])
            if sub == "cp":
                # A container path can be the bind-mounted host .env.
                for path in rest:
                    path = path.split(":", 1)[-1]
                    if self.is_secret(path):
                        self.block_secret(path)
            inner = docker_inner_command(words[1:])
            if inner:
                self.check_container_env(inner, depth + 1)
                self.check_simple_command(inner, sql_text, depth + 1, full_text)

    def check_assignment(self, assignment):
        name, _, value = assignment.partition("=")
        if name == "UV_ENV_FILE" and any(self.is_secret(v) for v in value.split()):
            self.blocked.append(
                f"--env-file/UV_ENV_FILE {value} loads that file's secrets into the "
                "program's environment, like `dotenv run`. Drop it: the app reads "
                ".env itself."
            )
        for rule_name, allow, reason in self.env_rules:
            if name == rule_name and not allow.search(value):
                self.blocked.append(reason)

    def check_find(self, words, depth):
        """find ... -name .env -exec cat {} or -delete acts on the secret file."""
        expr = find_expression(words)
        for i, word in expr:
            if word in FIND_ACTIONS - {"-delete"}:
                # `-exec cat .env ;` and `-exec sh -c '...' ;` are commands too.
                end = next((j for j, _ in expr if j > i), len(words))
                command = words[
                    i + 1 : end - 1 if words[end - 1] in (";", "+") else end
                ]
                self.check_simple_command(command, " ".join(command), depth + 1)
            elif word in ("-fprint", "-fprint0", "-fprintf", "-fls"):
                if i + 1 < len(words) and self.is_secret(words[i + 1]):
                    self.block_secret(words[i + 1])  # it overwrites the file
        if not FIND_ACTIONS & set(words):
            return
        acts = "-delete" in words or any(
            os.path.basename((command_words(words[i + 1 :])[1] or ["ls"])[0])
            not in FIND_HARMLESS
            for i, word in enumerate(words)
            if word in FIND_ACTIONS
        )
        if not acts:
            return
        for k, (i, word) in enumerate(expr[:-1]):
            value = words[i + 1]
            if word in ("-name", "-iname"):
                secret = self.is_secret(value) or fnmatch.fnmatch(".env", value)
            elif word in ("-path", "-ipath", "-wholename"):
                secret = self.is_secret(value)
            else:
                continue
            if secret and not self.find_keeps_out(expr, k):
                self.block_secret(value)

    def find_keeps_out(self, expr, k):
        """True if the find test at expr[k] keeps what it matches from every action.

        `! -name '.env*'` and `-not -path './instance/*'` do, unless an -o after
        them gives the files they reject to another branch. `-not -path
        ./instance` does not: it skips the folder, not the files in it.
        `-path ./instance -prune -o ...` does, when an -o follows the -prune.
        """
        words = [w for _, w in expr]
        if FIND_ACTIONS & set(words[:k]):
            return False  # an action before the test already ran on the files
        negations = 0
        while negations < k and words[k - 1 - negations] in ("!", "-not"):
            negations += 1
        if negations % 2 == 0:
            return negations == 0 and find_prunes(words, k)
        depth = low = 0
        for word in words[k + 2 :]:
            if word == "(":
                depth += 1
            elif word == ")":
                depth -= 1
                low = min(low, depth)
            elif word in ("-o", "-or", ",") and depth <= low:
                return False
        test, value = words[k], words[k + 1]
        if test in ("-path", "-ipath", "-wholename") and value.endswith("*"):
            return True  # the pattern also matches everything under the folder
        return not self.is_secret(re.sub(r"[*?]+$", "", value) + "/x")

    def check_container_script(self, script, depth):
        """Check a script that a shell inside a container runs."""
        for pipeline in split_pipelines(strip_heredocs(script)[0]):
            for tokens in pipeline:
                self.check_container_env(tokens, depth)

    def check_container_env(self, tokens, depth):
        """Block printing a container's environment, which holds .env values."""
        while tokens and (
            ASSIGNMENT.match(tokens[0]) or tokens[0] in ("exec", "command", "nohup")
        ):
            tokens = tokens[1:]
        if not tokens or depth > 6:
            return
        program, args = os.path.basename(tokens[0]), tokens[1:]
        if program in SHELLS:
            for i, word in enumerate(args[:-1]):
                if word == "<<<" or re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", word):
                    self.check_container_script(args[i + 1], depth + 1)
                    break
            return
        operands, skip = [], False
        for arg in args:
            if skip:
                skip = False
            elif arg in ("-u", "--unset", "-C", "--chdir"):
                skip = True
            elif not arg.startswith("-"):
                operands.append(arg)
        if (
            (program == "env" and all(ASSIGNMENT.match(a) for a in operands))
            or (
                program == "printenv"
                and (not operands or any(SECRET_NAME.search(a) for a in operands))
            )
            or (
                program in ("echo", "printf")
                and any(SECRET_VAR.search(a) for a in args)
            )
        ):
            self.blocked.append(CONTAINER_ENV_REASON)

    def check_secret_files(self, program, args):
        args, redirects = split_redirects(args)
        for target in redirects:
            if self.is_secret(target):
                self.block_secret(target)

        if INTERPRETER.match(program):
            for arg in args:
                self.check_code(arg, program.startswith("python"))
            return
        if program == "git":
            self.check_git(args)
            return
        if program not in READERS:
            return

        excluded = []
        args = drop_excludes(program, args, excluded)
        pattern_given = False
        if program in PATTERN_FIRST:
            args, pattern_given = drop_patterns(program, args)
        files = [option_value(a) for a in args]
        files = [f for f in files if f is not None]
        if program in PATTERN_FIRST and not pattern_given:
            files = files[1:]
        self.check_tree(program, args, files, excluded)
        if program in COPIERS and len(files) >= 2:
            *sources, destination = files
            for source in sources:
                if self.is_secret(source):
                    self.block_secret(source)
            # Creating a secret file from its .example template is fine;
            # overwriting a real one is not. A destination the shell would
            # expand ($PWD/.env, ~/...) might exist, so treat it as existing.
            if self.is_secret(destination) and (
                not all(s.endswith(".example") for s in sources)
                or re.search(r"[$`~]", destination)
                or (self.cwd / destination).exists()
            ):
                self.block_secret(destination)
            return
        for path in files:
            if self.is_secret(path):
                self.block_secret(path)

    def check_tree(self, program, args, files, excluded):
        """`cp -r . /tmp/x`, `tar czf x.tgz .` or `zip -r x.zip .` copy the .env inside.

        Only the top level of each source folder is looked at.
        """
        if program in ("cp", "rsync", "scp"):
            sources = [(self.cwd, f) for f in files[:-1]]
        elif program == "zip":
            sources = [(self.cwd, f) for f in files[1:]]
        elif program == "tar" and any(
            a in ("-c", "--create") or re.fullmatch(r"-?[a-zA-Z]*c[a-zA-Z]*", a)
            for a in args[:1] + [a for a in args if a.startswith("-")]
        ):
            # -C dir and --directory=dir make the names after them relative to dir.
            sources, base, i = [], self.cwd, 0
            while i < len(args):
                arg = args[i]
                if arg in ("-C", "--directory") and i + 1 < len(args):
                    base, i = base / os.path.expanduser(args[i + 1]), i + 2
                    continue
                if arg.startswith("--directory="):
                    base = base / os.path.expanduser(arg.split("=", 1)[1])
                elif not arg.startswith("-"):
                    sources.append((base, arg))
                i += 1
        else:
            return
        for base, source in sources:
            source = re.sub(r"^\$(PWD|\{PWD\})(?=/|$)", str(self.cwd), source)
            folder = base / os.path.expanduser(source)
            if re.search(r"[$`*?\[]", source) or not folder.is_dir():
                continue
            try:
                entries = list(itertools.islice(os.scandir(folder), 2000))
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if any(p.search(name) for p in self.secret_paths) and not any(
                    excludes(program, p, name, entry.is_dir()) for p in excluded
                ):
                    hint = f"-x '{name}*'" if program == "zip" else f"--exclude {name}"
                    self.blocked.append(
                        f"{source} holds {name}, which has local secrets, so this "
                        f"copies it. Add {hint}, or copy only the folders you need."
                    )

    def check_git(self, args):
        """git diff/grep --no-index read any file; git add --force stages ignored ones."""
        words = [a for a in args if not a.startswith("-")]
        sub = next((w for w in words if w in ("diff", "grep", "add")), None)
        if sub is None:
            return
        after = args[args.index(sub) + 1 :]
        paths = [a for a in after if not a.startswith("-")]
        if sub in ("diff", "grep") and "--no-index" in after:
            pattern_given = any(
                a in PATTERN_OPTIONS or a.startswith(PATTERN_OPTION_PREFIXES)
                for a in after
            )
            if sub == "grep" and not pattern_given:
                paths = paths[1:]  # the first positional is the pattern
        elif sub == "add" and any(
            re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*|--force", a) for a in after
        ):
            if (
                not paths
                or any(re.fullmatch(r"-[a-zA-Z]*A[a-zA-Z]*|--all", a) for a in after)
                or any((self.cwd / p).is_dir() or set(p) & set("*?[") for p in paths)
            ):
                self.blocked.append(
                    "`git add --force` on a directory, a glob or -A stages every "
                    "ignored file, .env included. Name the files."
                )
        else:
            return
        for path in paths:
            if self.is_secret(path):
                self.block_secret(path)

    def check_code(self, code, python=False):
        """Look inside code, such as python -c "open('.env')", for secret files."""
        # Python code is split by Python's tokenizer, so a comment such as
        # "# don't read .env" is skipped and its apostrophe opens no string.
        parts = python_parts(code) if python else None
        if parts:
            code, strings = parts
        else:
            strings = " ".join(m.group(2) for m in STRING_LITERAL.finditer(code))
        for call in DOTENV_CALL.finditer(code):
            if not SAFE_ENV_FILE.search(code[call.end() :].split(")", 1)[0]):
                self.block_secret(".env")
                break
        # A bare name such as `instance` is a variable unless it is also in a
        # string or imported. Dotted module names are checked as paths.
        literals = set(CODE_WORD.findall(strings))
        modules = set()
        for match in IMPORT.finditer(code):
            modules.update(re.split(r"\s*,\s*", match.group(1) or match.group(2)))
        words = CODE_WORD.findall(code) + [m.replace(".", "/") for m in modules]
        for word in words:
            if word.isidentifier() and word not in literals | modules:
                continue
            if self.is_secret(word):
                self.block_secret(word)

    def is_secret(self, path):
        path = path.strip().lstrip("@")
        # The shell expands {a,b} and globs before the program sees them.
        return any(self.is_secret_word(word) for word in expand_braces(path))

    def is_secret_word(self, path):
        if any(pattern.search(path) for pattern in self.secret_paths):
            return True
        if not set(path) & set("*?["):
            return False
        expanded = os.path.expanduser(path)
        # A glob with wildcards in many folders can walk the disk for longer
        # than the hook timeout, so expand only shallow ones. zsh's ** matches
        # any number of folders, none included, which glob() can't follow. For
        # both, a last part that could match a .env name counts as secret.
        wild = sum(1 for part in expanded.split("/") if set(part) & set("*?["))
        deep = wild > 2 or (os.path.isabs(expanded) and wild > 1)
        last = os.path.basename(expanded)
        head = re.split(r"[*?[]", last, maxsplit=1)[0]
        could_be_env = (
            head != last
            and head.startswith(".")
            and (".env".startswith(head) or head.startswith(".env"))
        )
        if could_be_env and (deep or "**" in expanded):
            return True
        if deep:
            return False
        try:
            for variant in {expanded, expanded.replace("**/", "")}:
                pattern = os.path.join(glob.escape(str(self.cwd)), variant)
                for match in itertools.islice(glob.iglob(pattern), 1000):
                    relative = os.path.relpath(match, str(self.cwd))
                    if any(p.search(relative) for p in self.secret_paths):
                        return True
        except (OSError, ValueError):
            pass
        return False

    def block_secret(self, path):
        self.blocked.append(
            f"{path} holds local secrets. Don't read, copy, overwrite or delete it: "
            "ask the user for what you need, or use the .example file."
        )

    def block_sql(self):
        self.blocked.append(
            "DROP and TRUNCATE in a database client destroy data. Ask the user."
        )

    def block_redis(self):
        self.blocked.append("FLUSHALL and FLUSHDB wipe Redis. Ask the user.")


def compile_rules(rules):
    return [
        {
            "pattern": re.compile(rule["pattern"]),
            "unless": re.compile(rule["unless"]) if rule.get("unless") else None,
            "reason": rule["reason"],
        }
        for rule in rules
    ]


def rule_matches(rule, text):
    if not rule["pattern"].search(text):
        return False
    return not (rule["unless"] and rule["unless"].search(text))


def strip_heredocs(command):
    """Split heredoc bodies off a command, and drop comments and line continuations.

    Returns the command without the bodies, plus (pipeline that reads the body,
    whether the delimiter was quoted, body) for each one.
    """
    kept, pending, heredocs, stack = [], [], [], []
    lines, i = command.split("\n"), 0
    while i < len(lines):
        line, i = lines[i], i + 1
        if pending:
            delimiter, segment, quoted, body, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                heredocs.append((segment, quoted, "\n".join(body)))
                pending.pop(0)
            else:
                body.append(line)
            continue
        # Blank comments: an apostrophe in one would otherwise open a quote that
        # hides the next lines. Then an unescaped backslash at the end of the
        # line, outside single quotes, joins the next line.
        line, stack = blank_comment(line, stack)
        while (
            i < len(lines)
            and (len(line) - len(line.rstrip("\\"))) % 2
            and stack[-1:] not in (["'"], ["$'"])
        ):
            piece, stack = blank_comment(lines[i], stack, line[-2:-1] or "\n")
            line, i = line[:-1] + piece, i + 1
        kept.append(line)
        separators = [(m.start(), m.end()) for m in re.finditer(r";|&&|\|\|", line)]
        for m in HEREDOC.finditer(line):
            word = m.group(2)
            delimiter = UNQUOTE.sub(lambda q: "".join(filter(None, q.groups())), word)
            start = max([e for s, e in separators if e <= m.start()], default=0)
            stop = min([s for s, e in separators if s >= m.end()], default=len(line))
            pending.append(
                (delimiter, line[start:stop], word != delimiter, [], bool(m.group(1)))
            )
    # The shell reads an unterminated heredoc to the end of the command. Check
    # those lines as its input and, in case the << was not a heredoc (inside
    # quotes, or $((x<<y))), as commands too.
    for _, segment, quoted, body, _ in pending:
        heredocs.append((segment, quoted, "\n".join(body)))
        kept.extend(body)
    return "\n".join(kept), heredocs


def blank_comment(line, stack, prev="\n"):
    """Blank a `# comment` in one line of a command, keeping every offset.

    stack carries the quotes and substitutions left open by earlier lines and
    is returned updated. prev is the character before the line, for a line
    joined by a backslash continuation.
    """
    stack, i, closed = list(stack), 0, -2
    while i < len(line):
        c, top = line[i], (stack[-1] if stack else None)
        if top in ("'", "$'"):
            end = i
            while end < len(line) and line[end] != "'":
                end += 2 if top == "$'" and line[end] == "\\" else 1
            if end >= len(line):
                break
            stack.pop()
            i = end + 1
            continue
        if c == "\\":
            i += 2
            continue
        if line.startswith("$(", i):
            stack.append("(")
            i += 2
            continue
        if top == '"':
            if c == '"':
                stack.pop()
            elif c == "`":
                stack.append("`")
        elif c == "'":
            stack.append("$'" if i > 0 and line[i - 1] == "$" else "'")
        elif c == '"':
            stack.append('"')
        elif c == "`":
            if top == "`":
                stack.pop()
            else:
                stack.append("`")
        elif c == "(" and top == "(":
            stack.append("(")
        elif c == ")" and top == "(":
            stack.pop()
            closed = i
        elif (
            c == "#"
            and (line[i - 1] if i else prev) in " \t\n;&|()"
            and closed != i - 1
        ):
            return line[:i] + " " * (len(line) - i), stack
        i += 1
    return line, stack


def blank_single_quoted(command, heredoc=False):
    """Return command with the inside of '...' blanked, keeping every offset.

    $(...) and backticks start a new quoting level even inside "...". In a
    heredoc body quotes are ordinary characters, but $(...) still expands.
    Unbalanced quotes leave the rest unchanged, so the guard stays strict.
    """
    out, i = list(command), 0
    stack = ["<<"] if heredoc else []  # also holds '"', "(" and "`"
    while i < len(command):
        c, top = command[i], (stack[-1] if stack else None)
        if c == "\\":
            if command[i + 1 : i + 2] in ("`", "$"):
                out[i + 1] = " "  # an escaped ` or $ is literal
            i += 2
            continue
        if command.startswith("$(", i):
            stack.append("(")
            i += 2
            continue
        if top in ('"', "<<"):
            if c == top:
                stack.pop()
            elif c == "`":
                stack.append("`")
            elif c in "<>" and command[i + 1 : i + 2] == "(":
                out[i] = " "  # "<(" inside double quotes is literal text
        elif c == "'":
            end = i + 1
            if i > 0 and command[i - 1] == "$":  # $'...' allows \' inside
                while end < len(command) and command[end] != "'":
                    end += 2 if command[end] == "\\" else 1
            else:
                end = command.find("'", end)
            if end < 0 or end >= len(command):
                break
            out[i + 1 : end] = " " * (end - i - 1)
            i = end
        elif c == '"':
            stack.append('"')
        elif c == "`":
            if top == "`":
                stack.pop()
            else:
                stack.append("`")
        elif c == "(" and top == "(":
            stack.append("(")
        elif c == ")" and top == "(":
            stack.pop()
        i += 1
    return "".join(out)


def protect_quoted(command):
    """Swap quoted or escaped ( ) ; < > | & for placeholders.

    shlex returns '|' and \\( as the same token as an unquoted | or (, so
    `cut -d '|' -f1 .env` and `find . \\( -name .env \\) -delete` would be cut
    in two. split_pipelines puts the characters back in each word.
    """
    command = command.translate(NEUTRALIZE_PLACEHOLDERS)
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == "\\" and command[i + 1 : i + 2] not in ("", "\n"):
            out.append(c + QUOTED_PUNCTUATION.get(command[i + 1], command[i + 1]))
            i += 2
            continue
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in "'\"":
            quote = c
        if quote and c in QUOTED_PUNCTUATION:
            c = QUOTED_PUNCTUATION[c]
        out.append(c)
        i += 1
    return "".join(out)


def split_pipelines(command):
    """Split a command line into pipelines of simple commands (token lists)."""
    try:
        lexer = shlex.shlex(
            protect_quoted(command), posix=True, punctuation_chars=PUNCTUATION
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        # Unbalanced quotes: fall back to a rough split, as one pipeline.
        return [[part.split() for part in re.split(r"[;&|()\n]+", command)]]

    pipelines, pipeline, current = [], [], []
    for token in tokens:
        if token and all(c in PUNCTUATION for c in token) and not is_redirect(token):
            if current:
                pipeline.append(current)
            current = []
            if token not in ("|", "|&"):
                if pipeline:
                    pipelines.append(pipeline)
                pipeline = []
            if not pipeline and re.fullmatch(r"\)*\|&?", token):
                pipeline.append([])  # the next command reads a ( ) group's output
        elif token and all(ord(c) in RESTORE_PUNCTUATION for c in token):
            current.append(Literal(token.translate(RESTORE_PUNCTUATION)))
        else:
            current.append(token.translate(RESTORE_PUNCTUATION))
    if current:
        pipeline.append(current)
    if pipeline:
        pipelines.append(pipeline)
    return pipelines


def expand_braces(word, limit=64):
    """Bash brace expansion, enough for '.env{.example,}' and 'a{b,c}d'."""
    pending, words = [word], []
    for _ in range(4096):
        if not pending or len(words) >= limit:
            break
        word = pending.pop()
        match = re.search(r"\{([^{}]*,[^{}]*)\}", word)
        if match:
            pending += [
                word[: match.start()] + part + word[match.end() :]
                for part in match.group(1).split(",")
            ]
        else:
            words.append(word)
    return words + pending


def python_parts(code):
    """Return (code with comments blanked, text of its string literals), or None.

    None when the hook's own Python can't parse the code (it may be older than
    the venv's), so the caller falls back to a rough scan. In an f-string only
    the literal text counts, not {name}.
    """
    lines = io.StringIO(code).readlines()
    pieces = {getattr(tokenize, n, None) for n in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")}
    strings = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ast.parse(code)
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                (row, start), (end_row, end) = tok.start, tok.end
                line = lines[row - 1]
                if end_row != row or line[start:end] != tok.string:
                    return None
                lines[row - 1] = line[:start] + " " * (end - start) + line[end:]
            elif tok.type == tokenize.STRING:
                text = tok.string
                if "f" in re.match(r"[A-Za-z]*", text).group().lower():
                    for _ in range(5):
                        text = re.sub(r"\{[^{}]*\}", " ", text)
                strings.append(text)
            elif tok.type in pieces:
                strings.append(tok.string)
    except (
        tokenize.TokenError,
        SyntaxError,
        ValueError,
        IndexError,
        RecursionError,
        MemoryError,
    ):
        return None
    return "".join(lines), " ".join(strings)


def find_expression(words):
    """The words of a find command as (index, word), each -exec ... ; or +
    folded into its first word, so its arguments can't pass for ( ) or -o."""
    expr, i = [], 1
    while i < len(words):
        expr.append((i, words[i]))
        if words[i] in FIND_ACTIONS - {"-delete"}:
            while i + 1 < len(words) and words[i + 1] not in (";", "+"):
                i += 1
            i += 1
        i += 1
    return expr


def find_prunes(words, i):
    """True if -prune runs on everything the find test at words[i] matches, and
    an -o after it keeps those entries from the rest of the expression.

    Only -a and ) may come between them, or the other choices of an -o in a
    ( ) group around the test, as in `\\( -path ./instance -o -path ./.venv \\)
    -prune -o`. A test there, as in `-name .env -type d -prune`, may be false.
    """
    level = words[:i].count("(") - words[:i].count(")")
    pruned, j = False, i + 2
    while j < len(words):
        word = words[j]
        if word in ("-o", "-or") and level > 0:
            # The test made this group true: skip its other choices.
            depth = 0
            while j + 1 < len(words) and depth >= 0:
                j += 1
                depth += {"(": 1, ")": -1}.get(words[j], 0)
            level -= 1
        elif word in ("-o", "-or"):
            return pruned
        elif word == ")":
            level -= 1
        elif word == "-prune" and not pruned:
            pruned = True
        elif word not in ("-a", "-and"):
            return False
        j += 1
    return pruned


def runs_stdin(words):
    """True if words run code read from stdin, as a heredoc would give it.

    `python3`, `python3 -u -`, `python manage.py shell`, `sh` and `docker
    compose exec -T web sh` do. With -c, -m or -e the code is an argument and
    stdin is only data.
    """
    if words and os.path.basename(words[0]) in ("docker", "docker-compose"):
        words = command_words(docker_inner_command(words[1:]))[1]
    if not words:
        return False
    program = os.path.basename(words[0])
    if program in SHELLS:
        code = r"-[a-zA-Z]*c"
    elif program.startswith("python"):
        code = r"-[^-WX]*[cm]"  # -c, -m, -uc, -Im; but not -X importtime
    elif INTERPRETER.match(program):
        code = r"-[a-zA-Z]*[eEpr]|--(eval|print)\b"
    else:
        return False
    for word in words[1:]:
        if word == "-" or not word.startswith("-"):
            break
        if re.match(code, word):
            return False
    return True


def printed_text(tokens):
    """What one simple command prints, if it is echo or printf; else ""."""
    words = split_redirects(command_words(tokens)[1])[0]
    args = words[1:]
    if not args or words[0] not in ("echo", "printf"):
        return ""
    if words[0] == "echo":
        while args and re.fullmatch(r"-[neE]+", args[0]):
            args = args[1:]
        text = " ".join(args)
    else:  # the format without its %s, then each argument on its own line
        text = "\n".join([re.sub(r"%[-+ #0-9.]*[a-zA-Z]", "", args[0])] + args[1:])
    return text.replace("\\n", "\n")


def command_words(tokens):
    """Return (leading VAR=value assignments, words from the program name on)."""
    assignments, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        if ASSIGNMENT.match(token):
            assignments.append(token)
            i += 1
        elif os.path.basename(token) in RUNNERS and runner_start(tokens, i):
            j = runner_start(tokens, i)
            # `uv run --env-file .env` loads the file into the program's
            # environment, as UV_ENV_FILE=.env does; check_assignment checks both.
            for k in range(i + 1, j):
                option, eq, value = tokens[k].partition("=")
                if option == "--env-file":
                    value = value if eq else "".join(tokens[k + 1 : k + 2])
                    assignments.append("UV_ENV_FILE=" + value)
            i = j
        elif token in PREFIX_WORDS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            if token == "timeout" and i < len(tokens):
                i += 1
        else:
            break
    return assignments, tokens[i:]


def runner_start(tokens, i):
    """Index of the program after `uv run [options]`, `uvx`, `poetry run` and the like.

    Returns 0 when tokens[i] does not run a program (`uv venv`, `uv pip install`).
    """
    base = os.path.basename(tokens[i])
    j = i + 1
    for step in ("global", "run"):
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] != "--":
            j += 2 if tokens[j] in RUNNER_VALUE_OPTIONS else 1
        if step == "global" and base != "uvx":
            if tokens[j : j + 2] == ["tool", "run"]:
                j += 1
            if tokens[j : j + 1] != ["run"]:
                return 0
            j += 1
    if tokens[j : j + 1] == ["--"]:
        j += 1
    return j if j < len(tokens) else 0


class Literal(str):
    """A word that was quoted punctuation, such as '|' or \\(."""


def is_redirect(token):
    return (
        not isinstance(token, Literal)
        and bool(token)
        and all(c in PUNCTUATION for c in token)
        and ("<" in token or ">" in token)
    )


def split_redirects(args):
    """Separate redirection targets (> file, < file) from ordinary arguments.

    Heredoc delimiters and here-strings are not files, so they are dropped.
    """
    plain, targets, i = [], [], 0
    while i < len(args):
        if is_redirect(args[i]):
            if i + 1 < len(args) and not args[i].startswith("<<"):
                targets.append(args[i + 1])
            i += 2
        else:
            plain.append(args[i])
            i += 1
    return plain, targets


def drop_excludes(program, args, excluded=None):
    """Drop exclude options and their values, which name files to skip.

    The values are added to excluded when it is given.
    """
    kept, i, excluded = [], 0, [] if excluded is None else excluded
    while i < len(args):
        arg = args[i]
        if program == "zip" and arg in ("-x", "--exclude"):
            i += 1  # zip's exclude list runs until the next option
            while i < len(args) and not args[i].startswith("-"):
                excluded.append(args[i])
                i += 1
        elif arg in EXCLUDE_OPTIONS:
            excluded.extend(args[i + 1 : i + 2])
            i += 2
        elif arg.startswith(tuple(o + "=" for o in EXCLUDE_OPTIONS)):
            excluded.append(arg.split("=", 1)[1])
            i += 1
        else:
            kept.append(arg)
            i += 1
    return kept


def excludes(program, pattern, name, is_dir):
    """Whether an exclude pattern keeps a top-level file or folder out of the copy.

    rsync never matches a leading ./, GNU tar ignores dir/, and zip -x dir or
    dir/ still copies the files inside the folder.
    """
    if pattern.startswith("./") and program != "rsync":
        pattern = pattern[2:]
    elif pattern.startswith("/") and program == "rsync":
        pattern = pattern[1:]  # anchored at the top of the transfer
    if is_dir and program == "zip":
        return fnmatch.fnmatchcase(name + "/x", pattern)
    if is_dir:
        pattern = re.sub(r"/\*\*?$" if program == "tar" else r"/(\*\*?)?$", "", pattern)
    return fnmatch.fnmatchcase(name, pattern)


def drop_patterns(program, args):
    """Drop -e/--regexp/--expression and their values, which are patterns.

    A -f value stays, because the program reads that file. Also returns whether
    an option gave the pattern, in which case the first operand is a file.
    """
    if program in ("jq", "yq"):  # -e is --exit-status; -f names a filter file
        return args, any(a in ("-f", "--from-file") for a in args)
    kept, given, i = [], False, 0
    while i < len(args):
        arg = args[i]
        if arg in INLINE_PATTERN_OPTIONS:
            given, i = True, i + 2
            continue
        if arg.startswith(("--regexp=", "--expression=", "-e")):
            given = True  # --regexp=X, -eX
        elif arg in ("-f", "--file") or arg.startswith(("--file=", "-f")):
            given = True
            kept.append(arg[2:] if re.fullmatch(r"-f.+", arg) else arg)  # -fX
        else:
            kept.append(arg)
        i += 1
    return kept, given


def option_value(arg):
    """The file part of an argument: '--file=x' -> 'x', 'if=x' -> 'x', '-n' -> None."""
    if arg.startswith("-"):
        return arg.split("=", 1)[1] if "=" in arg else None
    if "=" in arg and not arg.startswith(("/", ".")):
        return arg.split("=", 1)[1]
    return arg


def docker_subcommand(args):
    """For `docker [compose|container] [options] <sub> args...`, return (sub, args)."""
    i = 0
    while i < len(args):
        word = args[i]
        if word.startswith("-"):
            i += 2 if word in DOCKER_GLOBAL_VALUE_OPTIONS else 1
        elif word in ("compose", "container"):
            i += 1
        else:
            return word, args[i + 1 :]
    return None, []


def docker_inner_command(args):
    """For `docker [compose] exec|run [options] <target> cmd...`, return cmd."""
    sub, args = docker_subcommand(args)
    if sub not in ("exec", "run"):
        return []
    j = 0
    while j < len(args) and args[j].startswith("-"):
        j += 2 if args[j] in DOCKER_VALUE_OPTIONS else 1
    return args[j + 1 :]


def unique(items):
    return list(dict.fromkeys(items))


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") not in ("Bash", "Monitor"):
            return 0
        command = (payload.get("tool_input") or {}).get("command") or ""
        guard = Guard(load_config(), payload.get("cwd") or os.getcwd())
        decision, reasons = guard.decide(command)
    except Exception as exc:
        if os.environ.get("GUARD_BASH_STRICT"):
            raise
        print(
            f"guard_bash.py: internal error, command not checked: {exc!r}",
            file=sys.stderr,
        )
        return 0

    if decision == "block":
        print("Blocked by .claude/hooks/guard_bash.py:", file=sys.stderr)
        for reason in reasons:
            print(f"- {reason}", file=sys.stderr)
        return 2
    if decision == "ask":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": " ".join(reasons),
            }
        }
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
