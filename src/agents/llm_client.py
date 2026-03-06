"""LLM client abstraction: OllamaClient + GeminiClient."""
import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.now)


class LLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """Generate text completion."""
        ...

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> dict:
        """Generate and parse JSON output with retry."""
        ...

    async def health_check(self) -> bool:
        return True


class OllamaClient(LLMClient):
    """Local Ollama client — used for high-volume scoring tasks."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout: int = 120,
    ):
        self.base_url = base_url
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        start = time.monotonic()
        response = await self._client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        response.raise_for_status()
        data = response.json()
        elapsed = (time.monotonic() - start) * 1000
        return LLMResponse(
            content=data["response"],
            model=self.model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=elapsed,
        )

    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> dict:
        content = ""
        for attempt in range(max_retries):
            try:
                resp = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "system": system,
                        "stream": False,
                        "format": "json",  # Ollama built-in JSON mode
                        "options": {"temperature": temperature},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["response"]
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning("ollama_json_parse_failed", attempt=attempt + 1, preview=content[:200])
                if attempt == max_retries - 1:
                    return self._extract_json_fallback(content)
                await asyncio.sleep(1)
            except httpx.HTTPError as e:
                logger.error("ollama_http_error", attempt=attempt + 1, error=str(e))
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)
        return {}

    def _extract_json_fallback(self, text: str) -> dict:
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.error("ollama_json_fallback_failed", preview=text[:200])
        return {}

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


class GeminiClient(LLMClient):
    """Google Gemini client — used for summarization and scriptwriting."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self.model_name = model

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        from google.genai import types
        start = time.monotonic()
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system or None,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        elapsed = (time.monotonic() - start) * 1000
        return LLMResponse(
            content=response.text,
            model=self.model_name,
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            latency_ms=elapsed,
        )

    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> dict:
        from google.genai import types
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system or None,
                        temperature=temperature,
                        response_mime_type="application/json",
                    ),
                )
                return json.loads(response.text)
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    wait = 2**attempt
                    logger.warning("gemini_rate_limit", attempt=attempt + 1, wait_seconds=wait)
                    await asyncio.sleep(wait)
                elif attempt == max_retries - 1:
                    logger.error("gemini_generate_json_failed", error=str(e))
                    raise
                else:
                    await asyncio.sleep(1)
        return {}

    async def health_check(self) -> bool:
        try:
            from google.genai import types
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model_name,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            return bool(response.text)
        except Exception as e:
            logger.warning("gemini_health_check_failed", error=str(e))
            return False
