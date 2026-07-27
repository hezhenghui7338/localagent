"""Session-scoped provider/model selection for summarize LLM calls."""

from __future__ import annotations

from dataclasses import dataclass

from localagent import config


@dataclass(frozen=True)
class SummarizeModelChoice:
    provider: str = "auto"
    model: str = ""

    @classmethod
    def from_cli(
        cls,
        provider: str | None = None,
        model: str | None = None,
    ) -> SummarizeModelChoice:
        return cls(
            provider=config.normalize_provider_choice(provider or "auto"),
            model=(model or "").strip(),
        )

    @property
    def prefer(self) -> str | None:
        if self.provider == config.DEFAULT_MODEL_PROVIDER:
            return None
        return self.provider

    @property
    def model_override(self) -> str | None:
        return self.model or None

    def with_provider(self, provider: str) -> SummarizeModelChoice:
        return SummarizeModelChoice(
            provider=config.normalize_provider_choice(provider),
            model=self.model,
        )

    def with_model(self, model: str) -> SummarizeModelChoice:
        return SummarizeModelChoice(provider=self.provider, model=(model or "").strip())

    def config_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(frozen=True)
class SegmentSource:
    provider: str = ""
    model: str = ""
    via: str = "heuristic"  # llm | heuristic

    @classmethod
    def from_dict(cls, data: dict | None) -> SegmentSource | None:
        if not isinstance(data, dict):
            return None
        return cls(
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            via=str(data.get("via") or "heuristic"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "via": self.via,
        }


def format_source_label(source: SegmentSource) -> str:
    if source.via == "heuristic":
        from localagent.i18n import t

        return t("summarize.source_heuristic")
    if source.model:
        return f"{source.provider}/{source.model}"
    return source.provider or "unknown"


def append_source_footer(markdown: str, source: SegmentSource) -> str:
    from localagent.i18n import t

    body = (markdown or "").rstrip()
    if source.via == "heuristic":
        footer = t("summarize.source_footer_heuristic")
    else:
        footer = t("summarize.source_footer_llm", label=format_source_label(source))
    if not body:
        return f"{footer}\n"
    return f"{body}\n\n{footer}\n"
