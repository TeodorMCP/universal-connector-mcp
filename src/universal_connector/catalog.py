"""Built-in catalog of free/public APIs.

Two layers:

1. A small **curated** list of well-known, verified APIs (GitHub, Stripe,
   OpenAI, Wikipedia, ...) with working spec URLs and auth hints.
2. The **APIs.guru directory** (https://apis.guru) - a community-maintained
   index of 2500+ public OpenAPI specs (Google, AWS, Microsoft, Twilio, ...).
   Fetched lazily on first directory search and cached for the process
   lifetime.

The catalog is discovery-only: search results carry a ``spec`` URL (plus
optional ``base_url``/``protocol``) that the agent feeds to ``load_api``
unchanged. Nothing is loaded or executed from here, so the security guard
still applies at load/execute time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from universal_connector.config import USER_AGENT

GURU_LIST_URL = "https://api.apis.guru/v2/list.json"
_DESCRIPTION_LIMIT = 240


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    title: str
    description: str
    spec: str
    protocol: str | None = None
    base_url: str | None = None
    auth: str = "none"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_result(self, source: str, score: float) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "spec": self.spec,
            "auth": self.auth,
            "source": source,
            "score": round(score, 3),
        }
        if self.protocol:
            result["protocol"] = self.protocol
        if self.base_url:
            result["base_url"] = self.base_url
        return result


CURATED: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        name="github",
        title="GitHub REST API",
        description="Repositories, issues, pull requests, users, actions and everything else on GitHub.",
        spec="https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
        auth="optional GITHUB_TOKEN (higher rate limits, private data)",
        tags=("git", "repos", "issues", "code", "developer"),
    ),
    CatalogEntry(
        name="stripe",
        title="Stripe API",
        description="Payments, customers, subscriptions, invoices and billing.",
        spec="https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        auth="STRIPE_API_KEY required",
        tags=("payments", "billing", "finance", "subscriptions"),
    ),
    CatalogEntry(
        name="openai",
        title="OpenAI API",
        description="Chat completions, embeddings, images, audio and model management.",
        spec="https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        auth="OPENAI_API_KEY required",
        tags=("ai", "llm", "chat", "embeddings", "images"),
    ),
    CatalogEntry(
        name="gitlab",
        title="GitLab API",
        description="Projects, merge requests, pipelines and users on GitLab.",
        spec="https://gitlab.com/gitlab-org/gitlab/-/raw/master/doc/api/openapi/openapi_v3.yaml",
        base_url="https://gitlab.com/api/v4",
        auth="optional GITLAB_TOKEN",
        tags=("git", "repos", "ci", "devops"),
    ),
    CatalogEntry(
        name="wikipedia",
        title="Wikimedia REST API (English Wikipedia)",
        description="Article summaries, page content, media and metadata from Wikipedia.",
        spec="https://en.wikipedia.org/api/rest_v1/?spec",
        base_url="https://en.wikipedia.org/api/rest_v1",
        tags=("wiki", "encyclopedia", "knowledge", "search", "free"),
    ),
    CatalogEntry(
        name="open_meteo",
        title="Open-Meteo Weather Forecast API",
        description="Free weather forecasts. No API key needed. Sibling specs exist for air quality, climate, marine, flood and historical weather.",
        spec="https://raw.githubusercontent.com/open-meteo/open-meteo/main/openapi/forecast.yml",
        base_url="https://api.open-meteo.com",
        tags=("weather", "forecast", "climate", "free"),
    ),
    CatalogEntry(
        name="countries",
        title="Countries GraphQL API",
        description="Country, continent, currency and language data over GraphQL. No API key needed.",
        spec="https://countries.trevorblades.com/",
        protocol="graphql",
        base_url="https://countries.trevorblades.com/",
        tags=("countries", "geography", "graphql", "free"),
    ),
    CatalogEntry(
        name="httpbin",
        title="httpbin.org",
        description="HTTP request/response testing service. Useful for demos and debugging.",
        spec="https://httpbin.org/spec.json",
        base_url="https://httpbin.org",
        tags=("testing", "http", "echo", "demo", "free"),
    ),
    CatalogEntry(
        name="petstore",
        title="Swagger Petstore (demo)",
        description="The classic OpenAPI demo API. Good for trying out the connector.",
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        tags=("demo", "example", "testing", "free"),
    ),
)


def _score(entry: CatalogEntry, terms: list[str]) -> float:
    """Simple term-overlap scoring; name/tag hits weigh more than description hits."""
    haystack_name = entry.name.lower()
    haystack_title = entry.title.lower()
    haystack_tags = " ".join(entry.tags).lower()
    haystack_desc = entry.description.lower()
    score = 0.0
    for term in terms:
        if term in haystack_name:
            score += 3.0
        if term in haystack_title:
            score += 2.0
        if term in haystack_tags:
            score += 2.0
        if term in haystack_desc:
            score += 1.0
    return score


class Catalog:
    """Searchable index of ready-to-load public APIs."""

    def __init__(self, http_timeout: float = 30.0) -> None:
        self._http_timeout = http_timeout
        self._guru_entries: list[CatalogEntry] | None = None

    def search_curated(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = [t for t in query.lower().split() if t]
        scored = [(entry, _score(entry, terms)) for entry in CURATED]
        matches = [(e, s) for e, s in scored if s > 0]
        matches.sort(key=lambda pair: pair[1], reverse=True)
        return [e.to_result("curated", s) for e, s in matches[:limit]]

    async def search(
        self, query: str, limit: int = 10, include_directory: bool = True
    ) -> list[dict[str, Any]]:
        results = self.search_curated(query, limit)
        if include_directory and len(results) < limit:
            try:
                directory = await self._load_directory()
            except (httpx.HTTPError, ValueError):
                directory = []
            terms = [t for t in query.lower().split() if t]
            curated_specs = {r["spec"] for r in results}
            scored = [(entry, _score(entry, terms)) for entry in directory]
            matches = [
                (e, s) for e, s in scored if s > 0 and e.spec not in curated_specs
            ]
            matches.sort(key=lambda pair: pair[1], reverse=True)
            results.extend(
                e.to_result("apis.guru", s) for e, s in matches[: limit - len(results)]
            )
        return results

    async def _load_directory(self) -> list[CatalogEntry]:
        if self._guru_entries is not None:
            return self._guru_entries
        async with httpx.AsyncClient(
            timeout=self._http_timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(GURU_LIST_URL, follow_redirects=True)
            resp.raise_for_status()
            listing = resp.json()
        entries: list[CatalogEntry] = []
        for key, meta in listing.items():
            preferred = meta.get("preferred")
            versions = meta.get("versions", {})
            version = versions.get(preferred) or next(iter(versions.values()), None)
            if not version:
                continue
            spec_url = version.get("swaggerUrl") or version.get("swaggerYamlUrl")
            if not spec_url:
                continue
            info = version.get("info", {})
            description = (info.get("description") or "").strip()
            if len(description) > _DESCRIPTION_LIMIT:
                description = description[:_DESCRIPTION_LIMIT].rstrip() + "..."
            categories = info.get("x-apisguru-categories") or []
            entries.append(
                CatalogEntry(
                    name=key.replace(":", "_").replace(".", "_"),
                    title=info.get("title") or key,
                    description=description,
                    spec=spec_url,
                    tags=tuple(categories),
                )
            )
        self._guru_entries = entries
        return entries
