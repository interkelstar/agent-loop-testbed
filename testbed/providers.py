"""Provider + model catalog resolution.

The catalog is a plain JSON file (see ``providers.example.json``). It maps:

  providers  – an OpenAI-compatible chat/completions endpoint + how to auth it
  models     – a friendly name -> {provider, model_id, reasoning_replay?}
  suites     – named lists of model names to run together

API keys are read from environment variables named by the provider's
``api_key_env``. Nothing is read from disk or any vendor-specific store — bring
your own keys via the environment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    model_id: str
    base_url: str
    api_key_env: str
    reasoning_replay: bool
    label: str


class Catalog:
    def __init__(self, data: dict):
        self.providers = data.get("providers", {})
        self.models = data.get("models", {})
        self.suites = data.get("suites", {})

    @classmethod
    def load(cls, path: str) -> "Catalog":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def resolve(self, model_name: str) -> ModelSpec:
        m = self.models.get(model_name)
        if not m:
            raise KeyError(f"model '{model_name}' not in catalog")
        prov_name = m["provider"]
        prov = self.providers.get(prov_name)
        if not prov:
            raise KeyError(f"provider '{prov_name}' (for model '{model_name}') not in catalog")
        replay = m.get("reasoning_replay", prov.get("reasoning_replay_default", True))
        return ModelSpec(
            name=model_name,
            provider=prov_name,
            model_id=m.get("model_id", model_name),
            base_url=prov["base_url"],
            api_key_env=prov.get("api_key_env", ""),
            reasoning_replay=bool(replay),
            label=m.get("label", model_name),
        )

    def resolve_suite(self, names_or_suite: list[str]) -> list[ModelSpec]:
        """Expand a mixed list of model names and suite names into ModelSpecs."""
        out: list[ModelSpec] = []
        seen: set[str] = set()
        stack = list(names_or_suite)
        while stack:
            item = stack.pop(0)
            if item in self.suites:
                stack = list(self.suites[item]) + stack
                continue
            if item in seen:
                continue
            seen.add(item)
            out.append(self.resolve(item))
        return out

    def api_key(self, spec: ModelSpec) -> str:
        if not spec.api_key_env:
            return ""
        key = os.environ.get(spec.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"env {spec.api_key_env} is empty (needed for provider '{spec.provider}')"
            )
        return key
