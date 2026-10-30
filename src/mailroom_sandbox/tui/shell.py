"""Local interactive CLI; dispatches the existing parser, never a system shell."""
from __future__ import annotations

import argparse
import shlex
import sys


def children(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    return {name: child for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
            for name, child in action.choices.items()}


def command_catalog(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()) -> list[dict]:
    """One parser-derived catalog for completion, menus and browser manuals."""
    return [{"path": list(path), "help": parser.format_help(), "children": list(children(parser))},
            *[row for name, child in children(parser).items()
              for row in command_catalog(child, (*path, name))]]


def completions(line: str, catalog: list[dict]) -> list[str]:
    """Complete command paths only; quoted arguments are left to argparse."""
    try:
        tokens = shlex.split(line)
    except ValueError:
        return []
    if tokens[:1] == ["sandbox"]:
        tokens = tokens[1:]
    if tokens[:1] in (["help"], ["man"], ["menu"]):
        tokens = tokens[1:]
    if line.endswith(" "):
        parent, prefix = tokens, ""
    else:
        parent, prefix = tokens[:-1], tokens[-1] if tokens else ""
    node = next((row for row in catalog if row["path"] == parent), None)
    return [name for name in (node["children"] if node else []) if name.startswith(prefix)]


def run_shell(default_args: list[str] | None = None) -> int:
    from mailroom_sandbox import cli

    if not sys.stdin.isatty():
        raise cli.CLIUsageError("tui requires an interactive terminal; use sandbox --help in scripts")
    parser = cli.build_parser()
    catalog = command_catalog(parser)
    try:
        import readline
    except ImportError:
        readline = None
    old_completer = readline.get_completer() if readline else None
    if readline:
        def complete(text, state):
            matches = completions(readline.get_line_buffer(), catalog)
            return matches[state] if state < len(matches) else None
        readline.set_completer(complete)
        readline.parse_and_bind("bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete")
        readline.set_auto_history(False)
    history: list[str] = []
    menu: list[str] | None = None
    print("THE MAILROOM · local command terminal\nTab completes · ↑/↓ history · Ctrl+C interrupt · Ctrl+D exit\nhelp [command] · menu [command] · history · clear · exit\nExisting CLI spend/initials gates still apply. No persistent command history.")
    try:
        while True:
            try:
                line = input("mailroom> ").strip()
                if not line:
                    continue
                argv = shlex.split(line)
                if argv[:1] == ["sandbox"]:
                    argv = argv[1:]
                if not argv:
                    continue
                if argv[0] in {"exit", "quit"}:
                    return 0
                if argv == ["clear"]:
                    print("\033[2J\033[H", end="")
                    continue
                if argv == ["history"]:
                    print("\n".join(history))
                    continue
                # Never retain pasted credentials, even in this process's history.
                sensitive = any(word in line.lower() for word in ("token", "secret", "api-key", "sk-or-", "hf_"))
                if not sensitive:
                    history.append(line)
                    if readline:
                        readline.add_history(line)
                if menu is not None and argv == ["back"]:
                    argv = ["menu", *menu[:-1]]
                elif menu is not None and len(argv) == 1 and argv[0].isdigit():
                    node = next(row for row in catalog if row["path"] == menu)
                    index = int(argv[0]) - 1
                    if not 0 <= index < len(node["children"]):
                        print("error: select one of the listed numbers")
                        continue
                    argv = ["menu", *menu, node["children"][index]]
                if argv[0] == "menu":
                    path = argv[1:]
                    node = next((row for row in catalog if row["path"] == path), None)
                    if node is None:
                        print("error: unknown command path")
                        continue
                    menu = path
                    print(node["help"])
                    print("\n".join(f"{i}. {name}" for i, name in enumerate(node["children"], 1)))
                    print("Select a number · back · or type the full sandbox command to execute")
                    continue
                menu = None
                if argv[0] in {"help", "man"}:
                    argv = [*argv[1:], "--help"]
                if argv[0] == "tui":
                    print("Already in the Mailroom terminal.")
                    continue
                try:
                    rc = cli.main([*(default_args or []), *argv])
                except SystemExit as exc:
                    rc = exc.code
                if rc:
                    print(f"command exited {rc}")
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\nInterrupted · back at the prompt")
            except (ValueError, OSError) as exc:
                print(f"error: {exc}")
    finally:
        if readline:
            readline.set_completer(old_completer)
            readline.set_auto_history(True)


OPERATOR_CSS = """
.operator { margin: 16px 0; border: 1px solid var(--cyan); border-radius: 6px; background: #050f1a; }
.operator h2 { padding: 10px; margin: 0; color: var(--gold); font-size: 14px; border-bottom: 1px solid #294051; }
.operator .tools, .operator form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 10px; }
.operator input, .operator select, .operator button { font: inherit; color: var(--snow); background: #071a2e; border: 1px solid var(--cyan); padding: 8px; border-radius: 3px; max-width: 100%; }
.operator input { flex: 1; min-width: 140px; }
.operator pre { white-space: pre-wrap; overflow-wrap: anywhere; height: min(52vh, 560px); overflow: auto; padding: 16px; margin: 0; line-height: 1.6; }
.operator .hint { padding: 0 10px 10px; color: #b6c8d8; font-size: 11px; }
"""

OPERATOR_HTML = """
<section class="operator" data-view="terminal" hidden aria-labelledby="terminal-heading">
  <h2 id="terminal-heading">Command terminal</h2>
  <div class="tools"><button type="button" id="command-back">← Parent</button>
    <label>Command <select id="command-menu" aria-label="Nested CLI commands"></select></label>
    <span id="command-path">sandbox</span></div>
  <pre id="command-output" tabindex="0" aria-label="Command output">Loading command catalog…</pre>
  <form id="command-form"><label for="command-input">mailroom&gt;</label>
    <input id="command-input" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="help · status · config · campaign" aria-describedby="command-hint">
    <button type="submit">Enter</button></form>
  <div class="hint" id="command-hint">Tab completes · ↑/↓ history · Ctrl+L clears · Escape resets. Browser commands inspect live state and CLI manuals. Execute full commands locally with <code>sandbox tui</code>; no paid actions run from this page.</div>
</section>
"""

OPERATOR_JS = r"""
let operatorState = {};
let commandCatalog = [];
let commandPath = [];
const commandHistory = [];
let historyIndex = 0;
const commandOutput = document.getElementById("command-output");
const commandInput = document.getElementById("command-input");
function commandPrint(text) {
  commandOutput.textContent = (commandOutput.textContent + "\n" + text).slice(-24000);
  commandOutput.scrollTop = commandOutput.scrollHeight;
}
function commandNode(path) { return commandCatalog.find(row => JSON.stringify(row.path) === JSON.stringify(path)); }
function commandMenu(path) {
  const node = commandNode(path);
  if (!node) { commandPrint("Unknown command path. Type help."); return; }
  commandPath = path;
  document.getElementById("command-path").textContent = "sandbox " + path.join(" ");
  const menu = document.getElementById("command-menu");
  menu.replaceChildren(new Option(node.children.length ? "Choose subcommand…" : "Leaf command", ""));
  for (const child of node.children) menu.add(new Option(child, child));
  menu.disabled = !node.children.length;
  commandPrint(node.help);
}
document.getElementById("command-menu").addEventListener("change", ev => {
  if (ev.target.value) commandMenu([...commandPath, ev.target.value]);
});
document.getElementById("command-back").addEventListener("click", () => commandMenu(commandPath.slice(0, -1)));
function commandRun(line) {
  const words = line.trim().split(/\s+/).filter(Boolean);
  if (words[0] === "sandbox") words.shift();
  const name = words[0] || "help";
  if (/(?:token|secret|api.key|sk-or-|hf_)/i.test(line)) {
    commandPrint("Credentials are not accepted in the browser terminal. Configure them in your local environment.");
    return;
  }
  if (name === "clear") { commandOutput.textContent = ""; return; }
  commandPrint("mailroom> " + line);
  if (name === "history") { commandPrint(commandHistory.join("\n")); return; }
  commandHistory.push(line); if (commandHistory.length > 100) commandHistory.shift();
  historyIndex = commandHistory.length;
  const live = {status: operatorState.snapshot, config: operatorState.layout?.configuration,
    campaign: operatorState.campaign, services: operatorState.services, logs: operatorState.logs};
  if (Object.hasOwn(live, name)) {
    commandPrint(live[name] == null ? "Not available for the current run." : JSON.stringify(live[name], null, 2)); return;
  }
  if (["help", "man", "menu"].includes(name)) {
    if (words.length === 1) commandPrint("Live inspection: status · config · campaign · services · logs\nShell: help/man/menu [sandbox command path] · history · clear");
    commandMenu(words.slice(1)); return;
  }
  const path = words.filter(word => word !== "--help" && word !== "-h");
  if (commandNode(path)) { commandMenu(path); commandPrint("Run locally: sandbox " + path.join(" ")); return; }
  commandPrint("Not a browser inspection command. Use help [command path], or execute with sandbox tui locally.");
}
document.getElementById("command-form").addEventListener("submit", ev => {
  ev.preventDefault(); const line = commandInput.value; commandInput.value = ""; commandRun(line);
});
commandInput.addEventListener("keydown", ev => {
  if (ev.key === "Tab") {
    ev.preventDefault();
    const words = commandInput.value.trimStart().split(/\s+/);
    const prefix = words.pop() || "";
    if (["sandbox", "help", "man", "menu"].includes(words[0])) words.shift();
    const local = words.length ? [] : ["help", "man", "menu", "status", "config", "campaign", "services", "logs", "history", "clear"];
    const matches = [...new Set([...local, ...(commandNode(words)?.children || [])])].filter(name => name.startsWith(prefix));
    if (matches.length === 1) commandInput.value = commandInput.value.slice(0, commandInput.value.length - prefix.length) + matches[0] + " ";
    else commandPrint(matches.join("  ") || "No matching commands");
  } else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
    ev.preventDefault(); historyIndex = Math.max(0, Math.min(commandHistory.length, historyIndex + (ev.key === "ArrowUp" ? -1 : 1)));
    commandInput.value = commandHistory[historyIndex] || "";
  } else if (ev.key === "Escape") { commandInput.value = ""; }
  else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "l") { ev.preventDefault(); commandOutput.textContent = ""; }
});
fetch("/api/commands", {cache: "no-store"}).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
  .then(rows => { commandCatalog = rows; commandMenu([]); commandOutput.textContent = "THE MAILROOM · operator terminal\n\nLive commands    status · config · campaign · services · logs\nCLI navigation   help · man <command> · menu <command>\n\nChoose a command above or type help to begin.\nFull CLI execution: sandbox tui in your local terminal."; })
  .catch(err => { commandOutput.textContent = "Command catalog unavailable: " + err.message; });
"""
