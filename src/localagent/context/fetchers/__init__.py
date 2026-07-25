"""JIT prefetch fetchers for turn-level context."""

from __future__ import annotations

from collections.abc import Callable

from localagent.context.fetchers.archive import prefetch_archive_context
from localagent.context.fetchers.aware import prefetch_aware_context
from localagent.context.fetchers.personal import prefetch_personal_context
from localagent.context.fetchers.session import prefetch_session_context
from localagent.context.fetchers.web import prefetch_web_context
from localagent.context.fetchers.work import prefetch_work_context
from localagent.context.fetchers.workspace import prefetch_workspace_context
from localagent.context.router import PrefetchRoute, is_last_session_recall_query
from localagent.context.types import ContextBlocks
from localagent.i18n import t

StatusFn = Callable[[str], None] | None


def fetch_prefetch_blocks(
    user_message: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
    route: PrefetchRoute,
    *,
    on_status: StatusFn = None,
) -> tuple[ContextBlocks, dict[str, bool]]:
    """Run enabled prefetch modules and return raw blocks plus hit flags."""
    hits: dict[str, bool] = {}

    work_ctx = prefetch_work_context(session_id)
    if work_ctx:
        hits["work"] = True

    personal_context = ""
    if route.should_prefetch("personal"):
        personal_context = prefetch_personal_context(
            user_message,
            path=route.personal_path,
            route=route,
        )
        if personal_context:
            if on_status:
                on_status(t("chat.status_prefetch_personal"))
            hits["personal"] = True

    archive_context = ""
    if route.should_prefetch("archive"):
        archive_context = prefetch_archive_context(user_message, route=route)
        if archive_context:
            if on_status:
                on_status(t("chat.status_prefetch_archive"))
            hits["archive"] = True

    session_context = ""
    if route.should_prefetch("session"):
        session_context = prefetch_session_context(
            user_message, history, session_id, route=route
        )
        if session_context:
            if on_status:
                if is_last_session_recall_query(user_message):
                    on_status(t("chat.status_prefetch_last_session"))
                else:
                    on_status(t("chat.status_prefetch_session"))
            hits["session"] = True

    web_context = ""
    if route.should_prefetch("web"):
        web_context = prefetch_web_context(user_message, route=route)
        if web_context:
            if on_status:
                on_status(t("chat.status_prefetch_web"))
            hits["web"] = True

    workspace_ctx = ""
    if route.should_prefetch("workspace"):
        workspace_ctx = prefetch_workspace_context(user_message, route=route)
        if workspace_ctx:
            if on_status:
                on_status(t("chat.status_prefetch_workspace"))
            hits["workspace"] = True

    aware_ctx = ""
    if route.should_prefetch("aware"):
        aware_ctx = prefetch_aware_context(user_message, route=route)
        if aware_ctx:
            if on_status:
                on_status(t("chat.status_prefetch_aware"))
            hits["aware"] = True

    return (
        ContextBlocks(
            work=work_ctx,
            personal=personal_context,
            archive=archive_context,
            session=session_context,
            web=web_context,
            workspace=workspace_ctx,
            aware=aware_ctx,
        ),
        hits,
    )
