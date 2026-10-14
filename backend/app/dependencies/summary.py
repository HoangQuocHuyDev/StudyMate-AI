"""Lazy request-scoped dependency for Gemini document summaries."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.services.summary.concurrency import SummaryConcurrencyLimits
from app.services.summary.gemini_summary import (
    GeneratedSummary,
    GeminiSummaryProvider,
    SummaryProvider,
    SummaryStage,
    SummaryType,
)


@dataclass(frozen=True, slots=True)
class SummaryResources:
    provider: SummaryProvider
    concurrency_limits: SummaryConcurrencyLimits = SummaryConcurrencyLimits()
    deadline_seconds: float = 120.0


class _LazyGeminiSummaryProvider:
    """Delay SDK provider creation until a cache miss needs generation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider: GeminiSummaryProvider | None = None

    def generate_summary(
        self,
        content: str,
        summary_type: SummaryType,
        *,
        stage: SummaryStage,
        timeout_seconds: float | None = None,
    ) -> GeneratedSummary:
        return self._get_provider().generate_summary(
            content,
            summary_type,
            stage=stage,
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        if self._provider is not None:
            self._provider.close()

    def _get_provider(self) -> GeminiSummaryProvider:
        if self._provider is None:
            self._provider = GeminiSummaryProvider(self._settings)
        return self._provider


def get_summary_resources(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[SummaryResources]:
    """Yield a lazy provider and release its SDK client after the request."""

    provider = _LazyGeminiSummaryProvider(settings)
    try:
        yield SummaryResources(
            provider=provider,
            concurrency_limits=SummaryConcurrencyLimits(
                global_limit=settings.summary_global_concurrency,
                per_user_limit=settings.summary_user_concurrency,
            ),
            deadline_seconds=settings.summary_deadline_seconds,
        )
    finally:
        try:
            provider.close()
        except Exception:
            pass
