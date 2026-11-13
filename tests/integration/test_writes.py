from __future__ import annotations

from typing import Any

import pytest

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.safety.guard import SafetyError
from omv_mcp.tools.core import config_apply
from omv_mcp.tools.jobs_apt import cron_delete, cron_list, cron_run, cron_set
from omv_mcp.tools.network import rpc_call
from omv_mcp.tools.shares import (
    group_delete,
    group_get,
    group_set,
    nfs_share_delete,
    nfs_share_set,
    nfs_shares_list,
    rsyncd_module_delete,
    rsyncd_module_set,
    rsyncd_modules_list,
    shared_folder_create,
    shared_folder_delete,
    shared_folders_list,
    smb_share_delete,
    smb_share_set,
    smb_shares_list,
    user_delete,
    user_get,
    user_set,
)

pytestmark = pytest.mark.integration


async def _apply(ctx: Any, modules: list[str]) -> None:
    modules = [module for module in modules if module != "ssh"]
    if not modules:
        return
    plan = await config_apply(ctx, modules)
    assert isinstance(plan, PlanResponse)
    result = await config_apply(ctx, modules, confirm_token=plan.confirm_token)
    assert isinstance(result, OperationResult)


async def _execute(ctx: Any, tool: Any, **kwargs: Any) -> OperationResult:
    plan = await tool(ctx, **kwargs)
    assert isinstance(plan, PlanResponse)
    result = await tool(ctx, confirm_token=plan.confirm_token, **kwargs)
    assert isinstance(result, OperationResult)
    await _apply(ctx, result.dirtied_modules)
    return result


async def test_shared_folder_smb_roundtrip(ctx: Any) -> None:
    folders = await shared_folders_list(ctx, limit=1)
    mntentref = folders.items[0]["mntentref"]
    await _execute(ctx, shared_folder_create, name="it-share", mntentref=mntentref)
    found = await shared_folders_list(ctx, search="it-share")
    assert found.total == 1
    uuid = found.items[0]["uuid"]
    await _execute(
        ctx,
        smb_share_set,
        name="it-share",
        sharedfolderref=uuid,
        guest="no",
        comment="integration",
    )
    shares = await smb_shares_list(ctx, search="it-share")
    assert shares.total == 1
    await _execute(ctx, smb_share_delete, uuid=shares.items[0]["uuid"])
    await _execute(ctx, shared_folder_delete, uuid=uuid)


async def test_nfs_and_rsyncd_roundtrip(ctx: Any) -> None:
    folders = await shared_folders_list(ctx, limit=1)
    folder = folders.items[0]
    await _execute(
        ctx,
        nfs_share_set,
        sharedfolderref=folder["uuid"],
        mntentref=folder["mntentref"],
        client="127.0.0.1",
    )
    assert (await nfs_shares_list(ctx, search=folder["mntentref"])).total >= 0
    nfs = await nfs_shares_list(ctx, search=folder["uuid"])
    if nfs.items:
        await _execute(ctx, nfs_share_delete, uuid=nfs.items[0]["uuid"])

    await _execute(
        ctx,
        rsyncd_module_set,
        name="itmod",
        sharedfolderref=folder["uuid"],
    )
    modules = await rsyncd_modules_list(ctx, search="itmod")
    assert modules.total == 1
    await _execute(ctx, rsyncd_module_delete, uuid=modules.items[0]["uuid"])


async def test_users_and_groups(ctx: Any) -> None:
    await _execute(
        ctx,
        user_set,
        name="tester2",
        groups=["users"],
        shell="/usr/sbin/nologin",
        comment="integration",
    )
    assert (await user_get(ctx, "tester2"))["name"] == "tester2"
    await _execute(ctx, group_set, name="itgroup", comment="integration", members=[])
    assert (await group_get(ctx, "itgroup"))["name"] == "itgroup"
    await _execute(ctx, user_delete, name="tester2")
    await _execute(ctx, group_delete, name="itgroup")


async def test_cron_and_config_refusal(ctx: Any) -> None:
    await _execute(
        ctx,
        cron_set,
        command="true",
        comment="integration",
        execution="daily",
        minute=["0"],
        hour=["3"],
    )
    jobs = await cron_list(ctx, search="integration")
    assert jobs.total == 1
    uuid = jobs.items[0]["uuid"]
    await cron_run(ctx, uuid)
    await _execute(ctx, cron_delete, uuid=uuid)
    with pytest.raises(SafetyError, match="modules is required"):
        await config_apply(ctx, None)
    with pytest.raises(SafetyError, match="modules is required"):
        await config_apply(ctx, [])


async def test_rpc_call_never_exposed(ctx: Any) -> None:
    with pytest.raises(SafetyError, match="never exposed"):
        await rpc_call(ctx, "DiskMgmt", "wipe", {})
