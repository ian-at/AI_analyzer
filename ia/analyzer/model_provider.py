from __future__ import annotations

from typing import Protocol, Any


class ModelProvider(Protocol):
    def name(self) -> str: ...
    def version(self) -> str: ...
    def enabled(self) -> bool: ...
    def analyze(self, run_id: str, group_id: str,
                entries: list[dict[str, Any]], history: dict[str, list[float]]) -> dict: ...


class K2ProviderAdapter:
    """适配现有 K2Client 到统一接口。"""

    def __init__(self, k2_client):
        self._k2 = k2_client

    def name(self) -> str:
        # 返回第一个启用的模型名称
        try:
            if hasattr(self._k2, 'models') and self._k2.models:
                # 返回优先级最高的模型
                enabled_models = [m for m in self._k2.models if m.enabled]
                if enabled_models:
                    return enabled_models[0].model
            # 回退到cfg中的model
            model_name = getattr(self._k2.cfg, "model", None)
            if model_name:
                return model_name
            return "ai-model"
        except Exception:
            return "ai-model"

    def version(self) -> str:
        try:
            if hasattr(self._k2, 'models') and self._k2.models:
                enabled_models = [m for m in self._k2.models if m.enabled]
                if enabled_models:
                    return enabled_models[0].name
            return getattr(self._k2.cfg, "model", "unknown") or "unknown"
        except Exception:
            return "unknown"

    def enabled(self) -> bool:
        return self._k2.enabled()

    def analyze(self, run_id: str, group_id: str, entries: list[dict[str, Any]], history: dict[str, list[float]], job_id: str = None) -> dict:
        return self._k2.analyze(run_id, group_id, entries, history, job_id=job_id)
