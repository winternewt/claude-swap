from unittest.mock import Mock

import pytest
from textual.widgets import DataTable

from claude_swap.models import AccountSnapshot, AccountsSnapshot
from claude_swap.tui.codex_watch import CodexWatchApp
from claude_swap.usage_store import UsageEntry


@pytest.mark.asyncio
async def test_watch_displays_and_switches_selected_codex_account(tmp_path):
    switcher = Mock(backup_dir=tmp_path)
    switcher.accounts_snapshot.return_value = AccountsSnapshot("1", tuple(
        AccountSnapshot(str(slot), f"user{slot}@example.test", "Plus", "",
                        slot == 1, "oauth", True, UsageEntry(last_good={"weekly": {"pct": 41}}))
        for slot in (1, 2)
    ), 1.0)
    app = CodexWatchApp(switcher)
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        assert "Weekly 41%" in str(table.get_cell("2", "quota"))
        table.move_cursor(row=1)
        await pilot.press("s")
        await app.workers.wait_for_complete()
        switcher.switch_to.assert_called_once_with("2", json_output=True)
        await pilot.press("d")
        await app.workers.wait_for_complete()
        switcher.set_account_disabled.assert_called_once_with("2", True)
