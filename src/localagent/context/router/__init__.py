"""JIT prefetch query detection and routing facade."""

from __future__ import annotations

from localagent.context.router.queries import (
    AWARE_QUERY,
    LOCATION_QUERY,
    PERSONAL_PROFILE_SIGNAL,
    WEB_DOMAIN,
    WEB_OVERRIDE,
    WEB_TEMPORAL,
    WORKSPACE_QUERY,
    PersonalPath,
    archive_search_query,
    archive_time_window,
    is_archive_recall_query,
    is_aware_query,
    is_family_query,
    is_last_session_recall_query,
    is_memory_browse_query,
    is_personal_query,
    is_session_recall_query,
    is_weak_archive_topic,
    is_web_query,
    is_workspace_query,
    personal_prefetch_path,
    web_blocked_by_personal,
    web_blocked_by_workspace,
)

_PREFETCH_EXPORTS = frozenset(
    {
        "BLOCKS",
        "CONFIDENCE_ANCHOR",
        "CONFIDENCE_BM25",
        "CONFIDENCE_DEFAULT",
        "CONFIDENCE_FORBID",
        "MODULE_CORPORA",
        "MODULE_PRIORITY",
        "PrefetchModule",
        "PrefetchRoute",
        "prefetch_header",
        "route_prefetch_modules",
    }
)


def __getattr__(name: str):
    if name in _PREFETCH_EXPORTS:
        from localagent.agent import prefetch_route

        return getattr(prefetch_route, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AWARE_QUERY",
    "BLOCKS",
    "CONFIDENCE_ANCHOR",
    "CONFIDENCE_BM25",
    "CONFIDENCE_DEFAULT",
    "CONFIDENCE_FORBID",
    "LOCATION_QUERY",
    "MODULE_CORPORA",
    "MODULE_PRIORITY",
    "PERSONAL_PROFILE_SIGNAL",
    "PrefetchModule",
    "PrefetchRoute",
    "PersonalPath",
    "WEB_DOMAIN",
    "WEB_OVERRIDE",
    "WEB_TEMPORAL",
    "WORKSPACE_QUERY",
    "archive_search_query",
    "archive_time_window",
    "is_archive_recall_query",
    "is_aware_query",
    "is_family_query",
    "is_last_session_recall_query",
    "is_memory_browse_query",
    "is_personal_query",
    "is_session_recall_query",
    "is_weak_archive_topic",
    "is_web_query",
    "is_workspace_query",
    "personal_prefetch_path",
    "prefetch_header",
    "route_prefetch_modules",
    "web_blocked_by_personal",
    "web_blocked_by_workspace",
]
