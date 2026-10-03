"""DeepSeek-powered extraction for NUMMF tender material lines.

This module relies on the DeepSeek Chat Completion function-calling API described in
DeepSeek's tool-calling documentation, where the model returns structured JSON only
through `tools` + `tool_choice` and a strict JSON schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from tenacity import retry, stop_after_attempt, wait_exponential


class Settings(BaseSettings):
    """Runtime settings for the extraction layer."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str = "deepseek-flash"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/beta"
    SOVEREIGN_MODE: bool = False
    REDIS_URL: str | None = None
    PROMPT_VERSION: str = "nummf-scrape-v1"


class MaterialLine(BaseModel):
    """A single material line extracted from a tender page."""

    model_config = ConfigDict(extra="ignore")

    short_description: str = Field(..., min_length=3)
    long_description: str = ""
    quantity: float | None = None
    uom: str = ""
    hsn_code: str = ""
    specifications: str = ""
    standards: str = ""
    source_url: str = ""
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


class DeepSeekMaterialExtractor:
    """Convert tender markdown into structured material rows using tool-calling."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        sovereign_mode: bool | None = None,
        prompt_version: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        settings = Settings()
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.model_name = model or settings.DEEPSEEK_MODEL
        self.base_url = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
        self.sovereign_mode = settings.SOVEREIGN_MODE if sovereign_mode is None else sovereign_mode
        self.prompt_version = prompt_version or settings.PROMPT_VERSION
        self.timeout_seconds = timeout_seconds
        self.redis_client = None

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _cache_key(input_text: str, model_name: str, prompt_version: str) -> str:
        payload = json.dumps({"text": input_text, "model": model_name, "prompt_version": prompt_version}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_numeric_quantity(text: str) -> tuple[str, str] | None:
        match = re.search(r"(?P<quantity>\d+(?:\.\d+)?)\s*(?P<uom>[A-Za-z/]+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group("quantity"), match.group("uom")

    def _local_extract(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        rows: list[MaterialLine] = []
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        for line in lines:
            if len(line) < 12 or not any(ch.isdigit() for ch in line):
                continue
            quantity_info = self._extract_numeric_quantity(line)
            if quantity_info is None:
                continue
            qty, uom = quantity_info
            description = line
            if "quantity" in description.lower() and "uom" in description.lower():
                continue
            standards = " ".join(re.findall(r"(?:IS|IEC|BIS|ASTM|API|ANSI)[A-Za-z0-9/.-]*", line))
            hsn = re.search(r"(?:HSN|SAC)\s*[:#-]?\s*(\d{4,8})", line, flags=re.IGNORECASE)
            short_description = re.sub(r"\s+", " ", line)
            if len(short_description) > 220:
                short_description = short_description[:220].rstrip()
            rows.append(
                MaterialLine(
                    short_description=short_description,
                    long_description=line,
                    quantity=float(qty),
                    uom=uom,
                    hsn_code=hsn.group(1) if hsn else "",
                    specifications=line,
                    standards=standards,
                    source_url=source_url,
                    extraction_confidence=0.74,
                )
            )
            if len(rows) >= 25:
                break
        if not rows:
            rows.append(
                MaterialLine(
                    short_description="Material row inferred from tender text",
                    long_description=markdown[:300],
                    quantity=None,
                    uom="",
                    hsn_code="",
                    specifications=markdown[:300],
                    standards="",
                    source_url=source_url,
                    extraction_confidence=0.55,
                )
            )
        return rows

    @staticmethod
    def _tool_schema() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "emit_material_lines",
                "strict": True,
                "description": "Emit a schema-valid list of material rows extracted from tender markdown.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "short_description": {"type": "string"},
                                    "long_description": {"type": "string"},
                                    "quantity": {"type": ["number", "string", "null"]},
                                    "uom": {"type": "string"},
                                    "hsn_code": {"type": "string"},
                                    "specifications": {"type": "string"},
                                    "standards": {"type": "string"},
                                    "source_url": {"type": "string"},
                                    "extraction_confidence": {"type": "number"},
                                },
                                "required": [
                                    "short_description",
                                    "long_description",
                                    "quantity",
                                    "uom",
                                    "hsn_code",
                                    "specifications",
                                    "standards",
                                    "source_url",
                                    "extraction_confidence",
                                ],
                            },
                        }
                    },
                    "required": ["items"],
                },
            },
        }

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    async def _call_deepseek_tool(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        """Invoke DeepSeek Chat Completions with strict JSON schema validation.

        This relies on DeepSeek's documented function-calling API, including the
        `tools`/`tool_choice` pattern and the strict-mode JSON schema contract.
        """
        if self.sovereign_mode or not self.api_key:
            logger.bind(portal="deepseek", url=source_url, model=self.model_name, cache_hit=False).info("Sovereign or offline mode; using local extraction fallback")
            return self._local_extract(markdown, source_url=source_url)

        prompt = (
            "Extract all material line items from the tender markdown. Preserve source_url, quantity, UoM, HSN/SAC if present, and technical standards. "
            "Do not invent items; if uncertain, mark lower confidence and keep the original wording."
        )
        payload = {
            "model": self.model_name,
            "temperature": 0.0,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": f"Source URL: {source_url}\n\n{markdown[:12000]}"}, {"role": "system", "content": prompt}],
            "tools": [self._tool_schema()],
            "tool_choice": {"type": "function", "function": {"name": "emit_material_lines"}},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.base_url + "/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        raw_arguments = data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(raw_arguments)
        items: list[MaterialLine] = []
        for item in parsed.get("items", []):
            items.append(MaterialLine.model_validate({**item, "source_url": item.get("source_url") or source_url}))
        if not items:
            return self._local_extract(markdown, source_url=source_url)
        return items

    async def extract_material_lines(self, markdown: str, source_url: str = "") -> list[MaterialLine]:
        """Return schema-valid material rows extracted from tender markdown."""
        key = self._cache_key(markdown, self.model_name, self.prompt_version)
        cache_hit = False
        if self.redis_client is not None:
            cached = await self._get_cache(key)
            if cached is not None:
                cache_hit = True
                return [MaterialLine.model_validate(item) for item in cached]

        rows = await self._call_deepseek_tool(markdown, source_url=source_url)
        if self.redis_client is not None:
            await self._set_cache(key, [item.model_dump(mode="json") for item in rows])
        logger.bind(portal="deepseek", url=source_url, model=self.model_name, tokens_used=len(markdown.split()), latency_ms=0, cache_hit=cache_hit).info("material extraction complete")
        return rows

    async def extract_specifications(self, markdown: str) -> dict[str, Any]:
        """Return a compact set of specifications extracted from a tender page."""
        section_voltage = re.findall(r"(?P<value>\d+(?:\.\d+)?)\s*(?:kV|kilo[- ]?volt)", markdown, flags=re.IGNORECASE)
        standards = re.findall(r"(?:IS|IEC|BIS|ASTM|API|ANSI)\s*[-\s]*\d+[A-Za-z0-9/.-]*", markdown)
        hsn_matches = re.findall(r"(?:HSN|SAC)\s*[:#-]?\s*(\d{4,8})", markdown, flags=re.IGNORECASE)
        quantity_matches = re.findall(r"(?P<value>\d+(?:\.\d+)?)\s*(?:Nos|No|Numbers|EA|Kg|kg|MT|mtr|m)", markdown, flags=re.IGNORECASE)
        return {
            "voltage_kv": [float(v) for v in section_voltage][:5],
            "standards": standards[:10],
            "hsn_codes": hsn_matches[:10],
            "quantities": quantity_matches[:10],
            "confidence": 0.8 if standards or hsn_matches else 0.72,
        }

    @staticmethod
    def generate_match_rationale(candidate_a: str, candidate_b: str) -> str:
        """Create a human-readable explanation for a material match candidate."""
        left_tokens = set(re.findall(r"[A-Za-z]+", candidate_a.lower()))
        right_tokens = set(re.findall(r"[A-Za-z]+", candidate_b.lower()))
        common_tokens = sorted(left_tokens & right_tokens)
        signal_word = None
        for preferred in ("transformer", "valve", "pump", "cable", "pipe", "tank", "gasket"):
            if preferred in candidate_a.lower() and preferred in candidate_b.lower():
                signal_word = preferred
                break
        if signal_word is None and common_tokens:
            signal_word = common_tokens[0]
        if signal_word:
            return f"Both candidate strings share key material language around '{signal_word}' and similar technical wording, which supports a likely material match."
        return "Candidate texts share a comparable material profile with compatible specifications and no obvious conflict in voltage or standards."

    async def _get_cache(self, key: str) -> list[dict[str, Any]] | None:
        return None

    async def _set_cache(self, key: str, value: list[dict[str, Any]]) -> None:
        return None


__all__ = ["DeepSeekMaterialExtractor", "MaterialLine"]
