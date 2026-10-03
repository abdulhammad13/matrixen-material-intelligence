# ADR: DeepSeek-powered material extraction for tender portals

- Status: Accepted
- Date: 2026-10-03

## Context

NUMMF needs to harvest live tender portals and convert messy HTML into structured material rows. The scraping layer must remain sovereign-first and must not rely on browser automation being embedded in the LLM itself.

## Decision

We use a layered architecture where the fetch layer runs on self-hosted infrastructure (Crawl4AI/Async HTTP + browser rendering when required), and the DeepSeek API is reserved for text understanding. All extraction calls use strict tool-call schemas and a confidence score. If `SOVEREIGN_MODE=true`, all external API calls are disabled and the system falls back to a local vLLM instance.

## Consequences

- Pros: deterministic extraction, easy schema validation, compliance with sovereign deployment constraints, clear provenance from source URL to extracted material row.
- Cons: requires careful caching and prompt versioning, and fetch layer must be resilient to site anti-bot protections.

## Rationale

This design aligns with the DeepSeek API documentation for function-calling and tool-call validation, while keeping fetch, crawl, and pricing controls inside the NUMMF infrastructure boundary.
