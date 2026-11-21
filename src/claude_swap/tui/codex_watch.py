"""Interactive watch over the same Codex account store as the CLI."""

import asyncio
import time
from functools import partial

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from claude_swap.codex import CodexAccountSwitcher, _codex_restart_hint
from claude_swap.menubar import usage_summary
from claude_swap.reset_credit_display import reset_credit_display
from claude_swap.settings import load_settings
from claude_swap.tui.data import ActionResult, run_action
from claude_swap.tui.modals import ConfirmModal


class CodexWatch(Screen):
    BINDINGS = [
        ("s", "switch", "Switch account"),
        ("d", "toggle_disabled", "Disable / enable"),
        ("a", "add_current", "Add current login"),
        ("x", "remove", "Remove account"),
        ("r", "refresh", "Refresh"),
        ("escape", "close", "Back"),
    ]

    def __init__(self, switcher=None):
        super().__init__()
        self.switcher = switcher or CodexAccountSwitcher()
        self.accounts = {}
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static("Codex accounts", id="codex-status", markup=False)
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("Slot", "Account", "Plan", "State")
        table.add_column("Quota", key="quota")
        table.add_column("Banked resets", key="resets")
        table.focus()
        self.set_interval(load_settings(self.switcher.backup_dir).interval_seconds, self.action_refresh)
        self.set_interval(1, self._refresh_countdowns)
        self.action_refresh()

    @work
    async def _update(self, operation=None, switched=False):
        if self.busy:
            if operation:
                self.notify("Finishing the current refresh. Try again in a moment.")
            return
        self.busy = True
        try:
            outcome = await asyncio.to_thread(operation) if operation else None
            snapshot = await asyncio.to_thread(self.switcher.accounts_snapshot)
            if not self.is_mounted:
                return
            table = self.query_one(DataTable)
            current = self._selected()
            table.clear()
            self.accounts = {a.number: a for a in snapshot.accounts}
            for index, account in enumerate(snapshot.accounts):
                state = ", ".join(label for label, show in (
                    ("active", account.is_active), ("disabled", account.disabled),
                    ("unavailable", not account.switchable),
                ) if show)
                table.add_row(account.number, Text(account.email), Text(account.org_name),
                              state, "", "", key=account.number)
                if current and current.number == account.number:
                    table.move_cursor(row=index)
            self._refresh_countdowns()
            message = ("Codex accounts" if self.accounts else
                       "No saved accounts. Log in with codex, then press a to add that login.")
            if switched:
                message = await asyncio.to_thread(_codex_restart_hint)
            self.query_one("#codex-status", Static).update(message)
            if isinstance(outcome, ActionResult):
                if outcome.ok:
                    self.notify(outcome.first_line or "Done")
                else:
                    self.notify(outcome.first_line or "Failed", severity="error")
        except Exception as exc:
            if self.is_mounted:
                self.query_one("#codex-status", Static).update(str(exc))
        finally:
            self.busy = False

    def _refresh_countdowns(self):
        if not self.accounts:
            return
        table = self.query_one(DataTable)
        now = time.time()
        for account in self.accounts.values():
            entry = account.usage
            usage = entry.sentinel or entry.last_good
            if isinstance(usage, dict):
                usage = {k: v for k, v in usage.items() if k != "reset_credits"}
            summary = usage_summary(usage, now, fetched_at=entry.fetched_at)
            if entry.last_error:
                summary += f" · {entry.last_error}"
            reset = reset_credit_display(entry.last_good, now)
            expiry = Text("—")
            if reset:
                style = {"warning": "yellow", "critical": "bold red", "expired": "bold red"}
                prefix = "Last known: " if entry.last_error or entry.sentinel else ""
                expiry = Text(prefix + reset.text, style=style.get(reset.severity, ""))
            table.update_cell(account.number, "quota", Text(summary), update_width=True)
            table.update_cell(account.number, "resets", expiry, update_width=True)

    def _selected(self):
        table = self.query_one(DataTable)
        if table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            return self.accounts.get(key.value)
        return None

    def action_refresh(self):
        self._update()

    def action_switch(self):
        account = self._selected()
        if account and not account.is_active:
            self._update(partial(self.switcher.switch_to, account.number, json_output=True), switched=True)

    def action_toggle_disabled(self):
        account = self._selected()
        if account:
            self._update(partial(self.switcher.set_account_disabled, account.number, not account.disabled))

    def action_add_current(self):
        self.app.push_screen(
            ConfirmModal(
                "Save the current Codex login as a managed account?\n\n"
                "If this login is already managed, its stored credentials are refreshed in place.",
                title="Add Codex account",
                yes_label="Add",
            ),
            self._on_add_confirm,
        )

    def _on_add_confirm(self, confirmed):
        if confirmed:
            self._update(partial(run_action, self.switcher.add_account))

    def action_remove(self):
        account = self._selected()
        if account is None:
            return
        self.app.push_screen(
            ConfirmModal(
                f"Remove Codex account {account.number} ({account.email})?\n\n"
                "Its saved credentials are deleted. The live Codex login is not touched.",
                title="Remove Codex account",
                yes_label="Remove",
            ),
            partial(self._on_remove_confirm, account.number),
        )

    def _on_remove_confirm(self, number, confirmed):
        if confirmed:
            self._update(partial(run_action, partial(self.switcher.remove_account, number, assume_yes=True)))

    def action_close(self):
        if isinstance(self.app, CodexWatchApp):
            self.app.exit()
        else:
            self.app.pop_screen()


class CodexWatchApp(App):
    def __init__(self, switcher):
        super().__init__()
        self.switcher = switcher

    def on_mount(self):
        self.push_screen(CodexWatch(self.switcher))
