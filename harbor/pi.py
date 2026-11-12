from typing import Any
from harbor.agents.installed.pi import Pi, _CUSTOM_PROVIDER


class PiTinker(Pi):
    """Pi agent tailored for Tinker / custom OpenAI endpoints."""

    @classmethod
    def name(cls) -> str:
        return "pi-tinker"

    def _build_custom_models_json(
        self,
        access: Any,
        model_id: str,
    ) -> dict[str, Any] | None:
        try:
            models_json = super()._build_custom_models_json(access, model_id)
        except ValueError:
            endpoint = (
                getattr(access, "execution_base_url", None)
                or getattr(access, "resolved_base_url", None)
                or "http://127.0.0.1:8000/v1"
            )
            api_key = getattr(access, "api_key", None) or "EMPTY"
            models_json = {
                "providers": {
                    _CUSTOM_PROVIDER: {
                        "baseUrl": endpoint,
                        "apiKey": api_key,
                        "api": "openai-completions",
                        "models": [{"id": model_id}],
                    }
                }
            }

        if models_json:
            for provider in models_json.get("providers", {}).values():
                base_url = provider.get("baseUrl", "")
                if "127.0.0.1" in base_url or "localhost" in base_url:
                    provider["baseUrl"] = (
                        base_url.replace("127.0.0.1", "host.docker.internal")
                        .replace("localhost", "host.docker.internal")
                    )
                for model in provider.get("models", []):
                    # Force max model context length to 32k
                    model["contextWindow"] = 32768 + 16384
                    model["reasoning"] = True
                    # Prevent o3/o1 "developer" role conversion that triggers Tinker 422
                    model["compat"] = {
                        "supportsDeveloperRole": False,
                        "supportsReasoningEffort": True,
                    }
        return models_json
