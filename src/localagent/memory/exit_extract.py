"""Silent background memory extraction during chat sessions."""

from __future__ import annotations

import subprocess
import sys

from localagent.memory.save import confirm_save_facts
from localagent.memory.value_filter import filter_facts
from localagent.models.router import get_model_router
from localagent.persist.conversations import load_conversation


def _user_texts_from_messages(messages: list[dict]) -> list[str]:
    from localagent.session_commands import is_meta_user_content

    return [
        m["content"]
        for m in messages
        if m.get("role") == "user" and not is_meta_user_content(m.get("content", ""))
    ]


def extract_session_memories(
    session_id: str,
    *,
    interactive: bool | None = None,
) -> list[str]:
    """Extract candidate memories from a session and save with optional confirmation."""
    messages = load_conversation(session_id)
    user_texts = _user_texts_from_messages(messages)
    if not user_texts:
        return []

    combined = "\n".join(user_texts[-5:])
    try:
        facts = get_model_router().extract_facts(combined, context=f"session={session_id}")
    except Exception:
        return []

    facts = filter_facts(facts)
    if not facts:
        return []

    return confirm_save_facts(
        facts,
        metadata={"source": "chat", "session_id": session_id},
        title=f"从对话 {session_id} 提取到 {len(facts)} 条记忆",
        interactive=interactive,
    )


def schedule_session_memory_extract(session_id: str) -> None:
    """Extract and save session memories in a detached background process."""
    subprocess.Popen(
        [sys.executable, "-m", "localagent.memory.exit_extract", session_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m localagent.memory.exit_extract <session_id>", file=sys.stderr)
        return 2
    extract_session_memories(args[0], interactive=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
