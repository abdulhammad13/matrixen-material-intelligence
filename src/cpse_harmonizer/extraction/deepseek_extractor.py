"""Evidence-backed rule extraction with optional OpenAI-compatible DeepSeek enrichment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for optional extraction enrichment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str = "deepseek-flash"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_THINKING_MODE: bool = False
    SOVEREIGN_MODE: bool = True
    REDIS_URL: str | None = None
    PROMPT_VERSION: str = "nummf-scrape-v2"


class MaterialLine(BaseModel):
    """Extracted line with the original evidence span and explicit provenance."""

    model_config = ConfigDict(extra="forbid")

    short_description: str = Field(min_length=3)
    long_description: str = ""
    quantity: float | None = None
    uom: str = ""
    hsn_code: str = ""
    specifications: str = ""
    standards: str = ""
    source_url: str = ""
    evidence_text: str = ""
    source_page: int | None = Field(default=None, ge=1)
    source_section: str = ""
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return None
        return None


class DeepSeekMaterialExtractor:
    """Never synthesize rows; the local path emits only material-bearing evidence lines."""

    _MATERIAL_NOUN = re.compile(
        r"\b(?:valve|pump|pipe|flange|bearing|gasket|compressor|motor|cable|"
        r"transmitter|gauge|sensor|switchgear|transformer|panel|fitting|"
        r"instrument|tank|filter|coupling)\b",
        re.IGNORECASE,
    )
    _QUANTITY = re.compile(
        r"\b(?P<quantity>\d+(?:,\d{3})*(?:\.\d+)?)\s*"
        r"(?P<uom>nos?\.?|sets?|kg|kgs|mt|tonne|mtr|meter|metre|km|"
        r"litre|ltr|ea|each|pair|pairs|rolls?|spools?)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        sovereign_mode: bool | None = None,
        prompt_version: str | None = None,
        timeout_seconds: float = 30.0,
        thinking_mode: bool | None = None,
    ) -> None:
        settings = Settings()
        self.api_key = api_key if api_key is not None else settings.DEEPSEEK_API_KEY
        self.model_name = model or settings.DEEPSEEK_MODEL
        self.base_url = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
        if self.base_url.endswith("/beta"):
            self.base_url = self.base_url.removesuffix("/beta")
        self.sovereign_mode = settings.SOVEREIGN_MODE if sovereign_mode is None else sovereign_mode
        self.thinking_mode = settings.DEEPSEEK_THINKING_MODE if thinking_mode is None else thinking_mode
        self.prompt_version = prompt_version or settings.PROMPT_VERSION
        self.timeout_seconds = timeout_seconds
        self.max_retries = 3
        self.redis_client = None
        if settings.REDIS_URL:
            from redis.asyncio import Redis

            self.redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    @staticmethod
    def _cache_key(input_text: str, model_name: str, prompt_version: str, source_url: str = "") -> str:
        payload = json.dumps(
            {"text": input_text, "model": model_name, "prompt_version": prompt_version, "source_url": source_url},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _extract_numeric_quantity(cls, text: str) -> tuple[str, str] | None:
        match = cls._QUANTITY.search(text)
        return (match.group("quantity"), match.group("uom")) if match else None

    def _local_extract(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        items: list[MaterialLine] = []
        for line in (line.strip() for line in markdown.splitlines()):
            if len(line) < 12 or not self._MATERIAL_NOUN.search(line):
                continue
            quantity_match = self._QUANTITY.search(line)
            if not quantity_match:
                continue
            standards = " ".join(re.findall(r"\b(?:IS|IEC|BIS|ASTM|API|ANSI|ASME)\s*[-\s]?\d+[A-Za-z0-9/.-]*", line, re.I))
            hsn = re.search(r"\b(?:HSN|SAC)\s*[:#-]?\s*(\d{4,8})\b", line, re.I)
            items.append(
                MaterialLine(
                    short_description=re.sub(r"\s+", " ", line)[:220].rstrip(),
                    long_description=line,
                    quantity=float(quantity_match.group("quantity").replace(",", "")),
                    uom=quantity_match.group("uom"),
                    hsn_code=hsn.group(1) if hsn else "",
                    specifications=line,
                    standards=standards,
                    source_url=source_url,
                    evidence_text=line,
                    extraction_confidence=0.5,
                )
            )
            if len(items) == 25:
                break
        return items

    @staticmethod
    def _tool_schema() -> dict[str, Any]:
        fields = {
            "short_description": {"type": "string"},
            "long_description": {"type": "string"},
            "quantity": {"type": ["number", "string", "null"]},
            "uom": {"type": "string"},
            "hsn_code": {"type": "string"},
            "specifications": {"type": "string"},
            "standards": {"type": "string"},
            "evidence_text": {"type": "string"},
            "source_page": {"type": ["integer", "null"]},
            "source_section": {"type": "string"},
            "extraction_confidence": {"type": "number"},
        }
        return {
            "type": "function",
            "function": {
                "name": "emit_material_lines",
                "strict": True,
                "description": "Extract only material lines supported by source evidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": fields,
                                "required": list(fields),
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
            },
        }

    async def _call_deepseek_tool(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        if self.sovereign_mode or not self.api_key:
            logger.info("DeepSeek disabled or unconfigured; using evidence-backed local extraction.")
            return self._local_extract(markdown, source_url)
        prompt = (
            "Extract only material line items explicitly supported by the supplied document text. "
            "Copy an exact source line into evidence_text. Do not infer material rows from tender titles, "
            "administrative text, or missing values. Preserve quantities, units, HSN/SAC and standards exactly."
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0.0,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Source URL: {source_url}\n\n{markdown[:12000]}"},
            ],
            "tools": [self._tool_schema()],
            "tool_choice": (
                "auto"
                if self.thinking_mode
                else {"type": "function", "function": {"name": "emit_material_lines"}}
            ),
            "thinking": {"type": "enabled" if self.thinking_mode else "disabled"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response: httpx.Response | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        self.base_url + "/chat/completions",
                        headers=headers,
                        json=payload,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt + 1 == self.max_retries:
                    raise RuntimeError("DeepSeek request failed after bounded retries.") from exc
                await asyncio.sleep(min(2**attempt, 8))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 == self.max_retries:
                    raise RuntimeError(f"DeepSeek returned HTTP {response.status_code} after bounded retries.")
                await asyncio.sleep(min(2**attempt, 8))
                continue
            if response.is_error:
                raise RuntimeError(f"DeepSeek request rejected with HTTP {response.status_code}.")
            break
        if response is None:
            raise RuntimeError("DeepSeek request produced no response.")

        try:
            data = response.json()
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            calls = message.get("tool_calls") or []
            function = calls[0].get("function", {}) if calls else {}
            arguments = function.get("arguments")
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
                raise ValueError("No valid tool items array.")
        except (ValueError, TypeError, KeyError, IndexError):
            logger.warning("DeepSeek structured output was malformed; using evidence-backed local extraction.")
            return self._local_extract(markdown, source_url)

        extracted: list[MaterialLine] = []
        for item in parsed["items"]:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence_text")
            if not isinstance(evidence, str) or not evidence.strip() or evidence not in markdown:
                logger.warning("Discarded a material extraction without an exact source evidence span.")
                continue
            extracted.append(MaterialLine.model_validate({**item, "source_url": source_url}))
        return extracted

    async def extract_material_lines(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        key = self._cache_key(markdown, self.model_name, self.prompt_version, source_url)
        if self.redis_client is not None:
            cached = await self._get_cache(key)
            if cached is not None:
                return [MaterialLine.model_validate(item) for item in cached]
        rows = await self._call_deepseek_tool(markdown, source_url=source_url)
        if self.redis_client is not None:
            await self._set_cache(key, [item.model_dump(mode="json") for item in rows])
        logger.bind(model=self.model_name, rows=len(rows), cache_hit=False).info("Material extraction completed.")
        return rows

    async def extract_specifications(self, markdown: str) -> dict[str, Any]:
        voltages = re.findall(r"(\d+(?:\.\d+)?)\s*(?:kV|kilo[- ]?volt)", markdown, re.I)
        standards = re.findall(r"\b(?:IS|IEC|BIS|ASTM|API|ANSI)\s*[-\s]?\d+[A-Za-z0-9/.-]*", markdown, re.I)
        hsn = re.findall(r"\b(?:HSN|SAC)\s*[:#-]?\s*(\d{4,8})\b", markdown, re.I)
        return {
            "voltage_kv": [float(value) for value in voltages[:5]],
            "standards": standards[:10],
            "hsn_codes": hsn[:10],
            "evidence_status": "EXTRACTED_FROM_INPUT",
        }

    @staticmethod
    def generate_match_rationale(candidate_a: str, candidate_b: str) -> str:
        shared = sorted(set(re.findall(r"[A-Za-z]+", candidate_a.casefold())) & set(re.findall(r"[A-Za-z]+", candidate_b.casefold())))
        if not shared:
            return "No shared material terms were identified; expert review is required."
        return (
            f"Possible material match for review based on shared source-text terms: "
            f"{', '.join(shared[:8])}. This lexical evidence is not an approval."
        )

    async def _get_cache(self, key: str) -> list[dict[str, Any]] | None:
        if self.redis_client is None:
            return None
        cached = await self.redis_client.get(f"nummf:extract:{key}")
        return json.loads(cached) if cached else None

    async def _set_cache(self, key: str, value: list[dict[str, Any]]) -> None:
        if self.redis_client is not None:
            await self.redis_client.setex(
                f"nummf:extract:{key}",
                86400,
                json.dumps(value, ensure_ascii=False),
            )


__all__ = ["DeepSeekMaterialExtractor", "MaterialLine", "Settings"]
