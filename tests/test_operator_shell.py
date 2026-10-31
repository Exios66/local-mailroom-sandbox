"""Local command dispatch, recursive menus and parser-derived completion."""
import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.tui import shell


@pytest.fixture
def catalog():
    return shell.command_catalog(cli.build_parser())


def test_catalog_has_every_nested_path_and_manual(catalog):
    node = next(row for row in catalog if row["path"] == ["run", "start"])
    assert "--initials" in node["help"]
    assert next(row for row in catalog if row["path"] == ["run"])["children"]


@pytest.mark.parametrize(("line", "expected"), [
    ("run st", ["start", "status"]), ("sandbox run st", ["start", "status"]),
    ("help run sta", ["start", "status"]), ("menu run res", ["resume"]),
    ("run start ", []), ('run "unterminated', []),
])
def test_nested_completions(catalog, line, expected):
    assert shell.completions(line, catalog) == expected


def test_shell_dispatch_and_nested_numeric_menu(monkeypatch, capsys):
    monkeypatch.setattr(shell.sys.stdin, "isatty", lambda: True)
    entries = iter(["menu run", "1", "back", "help run start", "profiles", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))
    real = cli.main
    seen = []
    def dispatch(argv):
        seen.append(argv)
        return real(argv) if "--help" in argv else 0
    monkeypatch.setattr(cli, "main", dispatch)
    assert shell.run_shell() == 0
    output = capsys.readouterr().out
    assert "usage: sandbox run" in output and "Select a number" in output
    # "1" must open the first registered subcommand, not just reprint the run menu.
    assert "sandbox run preflight  (leaf command)" in output and "usage: sandbox run preflight" in output
    assert seen == [["run", "start", "--help"], ["profiles"]]


def test_shell_survives_parse_error_and_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(shell.sys.stdin, "isatty", lambda: True)
    entries = iter(["run start --max-items 0", "profiles", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))
    real = cli.main
    def dispatch(argv):
        if argv == ["profiles"]:
            raise KeyboardInterrupt
        return real(argv)
    monkeypatch.setattr(cli, "main", dispatch)
    assert shell.run_shell() == 0
    output = capsys.readouterr().out
    assert "command exited 2" in output and "Interrupted" in output


def test_tui_requires_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(shell.sys.stdin, "isatty", lambda: False)
    assert cli.main(["tui"]) == 2
    assert "interactive terminal" in capsys.readouterr().err


def test_tui_preserves_shared_cli_context(monkeypatch):
    seen = []
    monkeypatch.setattr(shell, "run_shell", lambda defaults: seen.extend(defaults) or 0)
    assert cli.main(["--profile", "ollama", "--model", "local-model", "tui",
                     "--agent-model", "sorter=override"]) == 0
    assert seen == ["--profile", "ollama", "--model", "local-model", "--agent-model", "sorter=override"]


def test_libedit_prefill_turns_off_history_recall_for_that_prompt(monkeypatch, capsys):
    import sys
    import types

    monkeypatch.setattr(shell.sys.stdin, "isatty", lambda: True)
    recalled = []
    fake = types.ModuleType("readline")
    fake.__doc__ = "Importing this module enables command line editing using libedit readline."
    fake.get_completer = lambda: None
    for name in ("set_completer", "parse_and_bind", "set_auto_history", "set_startup_hook"):
        setattr(fake, name, lambda *a, **k: None)
    fake.get_line_buffer = lambda: ""
    fake.add_history = recalled.append
    fake.clear_history = recalled.clear
    monkeypatch.setitem(sys.modules, "readline", fake)
    prompts = []
    entries = iter(["profiles", "menu eval pipeline", "2", "", "exit"])

    def typed(prompt):
        prompts.append((prompt, list(recalled)))
        return next(entries)

    monkeypatch.setattr("builtins.input", typed)
    monkeypatch.setattr(cli, "main", lambda argv: 0)
    assert shell.run_shell() == 0
    prompt, history = prompts[3]
    assert prompt == "mailroom> eval pipeline --class contract " and history == []
    # Recall comes back after the prefilled prompt.
    assert prompts[4][1] == ["profiles", "menu eval pipeline", "eval pipeline --class contract"]
