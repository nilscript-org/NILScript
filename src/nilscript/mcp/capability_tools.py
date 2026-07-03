"""Gate M6 — the five-tool capability plane (plan B7, UBCA Part X).

The model's tool surface never grows with the catalog: FIVE tools, regardless of how many
capabilities a tenant publishes. `discover` searches the catalog (published + exposure.ai only —
draft/hidden capabilities NEVER surface, fail closed); `inspect` returns one full contract;
`prepare` seeds a Permission Card; a HUMAN approves in Decisions; `execute` commits the signed
card; `schedule` registers a one-shot row the control-plane tick fires through the same path.

Discovery is PURE CODE (no LLM, no embeddings — ⛔ index-only upgrade later): exact/substring
alias match in both languages, word overlap with intent.en/ar + examples, optional domain filter.
Deterministic order; an honest empty result when nothing scores — never a fallback to raw verbs.

Like `AutomationTools`, this module never re-implements the registry — it relays authenticated
requests to the control plane, which owns the SSOT, the contracts, the strategy interpreter, and
the ONLY effect path. Refusals pass through as answers, never retried.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

# Word tokens for overlap scoring: latin word chars + the Arabic block, everything else a divider.
_TOKEN_RE = re.compile(r"[^\w؀-ۿ]+")

# Ranking weights — deterministic and dumb on purpose (aliases are captured from day one so a
# smarter index is a drop-in later; the CONTRACT of this function is order, not cleverness).
_SCORE_ALIAS_EXACT = 100
_SCORE_ALIAS_SUBSTRING = 60
_SCORE_INTENT_WORD = 5
_SCORE_EXAMPLE_WORD = 2
MAX_MATCHES = 8

EMPTY_DISCOVERY_MESSAGE = (
    "no capability matches this intent; do NOT fall back to raw verbs — the catalog is the whole "
    "lawful surface. Tell the user no published, AI-exposed capability covers this and stop."
)


def _norm(text: Any) -> str:
    return str(text or "").casefold().strip()


def _tokens(text: Any) -> set[str]:
    return {t for t in _TOKEN_RE.split(_norm(text)) if t}


def _score(body: dict[str, Any], text: str, words: set[str]) -> tuple[int, list[str]]:
    """One capability's discovery score against the normalized intent text: (a) alias exact/
    substring hits (both languages — aliases are free-text), (b) word overlap with intent.en/ar,
    (c) word overlap with examples. Pure, deterministic."""
    score = 0
    aliases_hit: list[str] = []
    for alias in body.get("aliases") or ():
        normed = _norm(alias)
        if not normed:
            continue
        if normed == text:
            score += _SCORE_ALIAS_EXACT
            aliases_hit.append(alias)
        elif normed in text or text in normed:
            score += _SCORE_ALIAS_SUBSTRING
            aliases_hit.append(alias)
    intent = body.get("intent") or {}
    intent_words = _tokens(intent.get("en")) | _tokens(intent.get("ar"))
    score += len(words & intent_words) * _SCORE_INTENT_WORD
    example_words: set[str] = set()
    for example in body.get("examples") or ():
        example_words |= _tokens(example)
    score += len(words & example_words) * _SCORE_EXAMPLE_WORD
    return score, aliases_hit


def rank_capabilities(
    records: list[dict[str, Any]],
    intent_text: str,
    domain: str | None = None,
    *,
    limit: int = MAX_MATCHES,
) -> list[dict[str, Any]]:
    """Rank a workspace's capability records against an intent. FAIL CLOSED on exposure: only
    state=published AND exposure.ai=true records are even scored — a draft or hidden capability
    never surfaces, whatever it would have scored. Zero-score records drop out (an empty list is
    the honest answer, not a padded one). Deterministic: sorted by (-score, capability_id)."""
    text = _norm(intent_text)
    words = _tokens(intent_text)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for rec in records:
        body = rec.get("body") or {}
        if rec.get("state") != "published":
            continue  # a draft/deprecated capability is not discoverable — fail closed
        if not ((body.get("exposure") or {}).get("ai") is True):
            continue  # exposure.ai=false is the default; flipping it is the governance act
        if domain and _norm(body.get("domain")) != _norm(domain):
            continue
        score, aliases_hit = _score(body, text, words)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                rec.get("capability_id") or "",
                {
                    "capability_id": rec.get("capability_id"),
                    "registry_version": rec.get("version"),
                    "version": body.get("version"),
                    "intent": body.get("intent") or {},
                    "domain": body.get("domain"),
                    "risk": body.get("risk"),
                    "strategy": body.get("strategy"),
                    "aliases_hit": aliases_hit,
                    "score": score,
                },
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


class CapabilityTools:
    """HTTP relay to the control-plane capability plane, workspace-pinned at construction (the
    tenant is the deployment's identity, never a model-chosen argument). Inject a client for
    tests. Auth is the registry bearer the MCP already holds (`NIL_REGISTRY_URL`/`_TOKEN`)."""

    def __init__(
        self,
        registry_url: str,
        token: str = "",
        *,
        workspace: str = "",
        agent: str = "ai-agent",
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base = registry_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._workspace = workspace
        self._agent = agent  # stamped as prepared_by — SoD refuses this identity's signature
        self._client = client
        self._timeout = timeout

    @classmethod
    def from_env(cls, *, workspace: str = "") -> CapabilityTools | None:
        """Build from `NIL_REGISTRY_URL`/`NIL_REGISTRY_TOKEN` (+ `NIL_WORKSPACE` fallback for the
        tenant pin), or None when no control plane is configured — the five tools then simply
        don't exist on this server, they never half-work."""
        url = os.environ.get("NIL_REGISTRY_URL", "")
        if not url:
            return None
        return cls(
            url,
            os.environ.get("NIL_REGISTRY_TOKEN", ""),
            workspace=workspace or os.environ.get("NIL_WORKSPACE", ""),
        )

    async def _request(
        self, method: str, path: str, *, json: Any = None, params: Any = None
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(base_url=self._base, timeout=self._timeout)
        try:
            resp = await client.request(
                method, path, json=json, params=params, headers=self._headers
            )
            try:
                return resp.json()
            except ValueError:
                return {"error": "non-json response", "status": resp.status_code}
        except httpx.HTTPError as exc:
            return {"error": f"control plane unreachable: {exc}"}
        finally:
            if self._client is None:
                await client.aclose()

    async def discover(self, intent_text: str, domain: str | None = None) -> dict[str, Any]:
        """Search the tenant catalog (published + exposure.ai only) — pure-code ranking, max 8."""
        listed = await self._request(
            "GET", "/capabilities", params={"workspace": self._workspace}
        )
        if "capabilities" not in listed:
            return listed  # the control plane's refusal/error IS the answer
        matches = rank_capabilities(listed["capabilities"], intent_text, domain)
        if not matches:
            return {"outcome": "empty", "matches": [], "message": EMPTY_DISCOVERY_MESSAGE}
        return {"outcome": "matches", "matches": matches}

    async def inspect(
        self, capability_id: str, version: int | None = None
    ) -> dict[str, Any]:
        """The full pinned definition + a summary of its approval strategy."""
        params: dict[str, Any] = {"workspace": self._workspace}
        if version is not None:
            params["version"] = version
        rec = await self._request("GET", f"/capabilities/{capability_id}", params=params)
        body = rec.get("body")
        if not isinstance(body, dict):
            return rec  # 404 / error envelope passes through
        strategy_rec = await self._request(
            "GET", f"/strategies/{body.get('strategy') or ''}",
            params={"workspace": self._workspace},
        )
        strategy_body = strategy_rec.get("body")
        return {
            "capability_id": rec.get("capability_id"),
            "registry_version": rec.get("version"),
            "state": rec.get("state"),
            "content_hash": rec.get("content_hash"),
            "definition": body,  # intent, typed inputs/outputs, risk, requires/creates/enables,
            #                      exposure, implemented_by — the whole contract, no hidden state
            "strategy": {
                "id": body.get("strategy"),
                "registry_version": strategy_rec.get("version"),
                "content_hash": strategy_rec.get("content_hash"),
                "root": (strategy_body or {}).get("root"),
            }
            if isinstance(strategy_body, dict)
            else {"id": body.get("strategy"), "error": strategy_rec.get("error")},
        }

    async def prepare(
        self, capability_id: str, inputs: dict[str, Any], version: int | None = None
    ) -> dict[str, Any]:
        """POST /prepared — the card envelope, or the contract refusal (INPUT_CONTRACT lists the
        offending fields) passed through as the answer."""
        payload: dict[str, Any] = {
            "workspace": self._workspace,
            "capability_id": capability_id,
            "inputs": inputs,
            "prepared_by": self._agent,
        }
        if version is not None:
            payload["version"] = version
        return await self._request("POST", "/prepared", json=payload)

    async def execute(self, prepared_id: str) -> dict[str, Any]:
        """POST /prepared/{id}/execute. NOT_APPROVED comes back as the answer — never retried."""
        out = await self._request(
            "POST", f"/prepared/{prepared_id}/execute", json={"workspace": self._workspace}
        )
        if (out.get("refusal") or {}).get("code") == "NOT_APPROVED":
            out["answer"] = (
                "awaiting signatures — a human must sign in Decisions; do not retry, do not "
                "work around the gate"
            )
        return out

    async def schedule(self, prepared_id: str, when: str) -> dict[str, Any]:
        """POST /prepared/{id}/schedule — a one-shot row the control-plane tick fires through
        the same execute path at/after `when` (ISO-8601, future only)."""
        return await self._request(
            "POST",
            f"/prepared/{prepared_id}/schedule",
            json={"workspace": self._workspace, "when": when},
        )
