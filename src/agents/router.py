"""Task-based LLM router: scoring → Ollama, summarization/scriptwriting → Gemini."""
import structlog

from src.agents.llm_client import GeminiClient, LLMClient, OllamaClient
from src.common.config import settings

logger = structlog.get_logger(__name__)

ROUTING: dict[str, str] = {
    "scoring": "ollama",
    "summarization": "gemini",
    "scriptwriting": "gemini",
}


class LLMRouter:
    def __init__(
        self,
        ollama: OllamaClient | None = None,
        gemini: GeminiClient | None = None,
    ):
        self._ollama = ollama or OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
        self._gemini = gemini or (
            GeminiClient(api_key=settings.gemini_api_key)
            if settings.gemini_api_key
            else None
        )
        self._clients: dict[str, LLMClient] = {"ollama": self._ollama}
        if self._gemini:
            self._clients["gemini"] = self._gemini

    def get_client(self, task: str) -> LLMClient:
        provider = ROUTING.get(task, "gemini")
        if provider not in self._clients:
            # Fallback to ollama if gemini not configured
            logger.warning("llm_fallback", task=task, requested=provider, using="ollama")
            return self._ollama
        return self._clients[provider]

    async def check_all(self) -> dict[str, bool]:
        results = {}
        for name, client in self._clients.items():
            results[name] = await client.health_check()
            logger.info("llm_health_check", provider=name, healthy=results[name])
        return results
