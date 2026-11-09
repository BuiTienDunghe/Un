"""Experimental branch: explicit local allowlist, checked before startup probes.

Unknown aliases are refused too: renaming a prohibited model must not bypass the
policy. This checks configured tags, not the authenticity of local weight files.
"""
ALLOWED = frozenset({"qwen3.5:2b", "lfm3:1.7b", "qwen3-embedding:0.6b",
                     "local-ai/glm-ocr:eot-v1", "glm-ocr:latest",
                     "local-ai/multilingual-e5-large:q8"})
OCR_ONLY = frozenset({"hf.co/prithivMLmods/ATH-MaaS-OvisOCR3-GGUF:Q8_0"})


def validate_small_model_routes(registry, overrides):
    from app.config.model_registry import ModelRegistryError
    for role in registry.roles:
        if role == "reranker":
            continue
        try:
            chain = registry.chain(role, overrides.pins.get(role))
        except ModelRegistryError as error:
            raise ModelRegistryError(f"MODEL_VERSION_{role.upper()}={overrides.pins.get(role)!r}: {error}") from error
        for record in chain:
            if "9b" in record.name.casefold():
                raise ValueError(f"Small-model branch refuses {role}: {record.name!r}")
            if role in overrides.disabled_roles:
                continue
            allowed = ALLOWED | (OCR_ONLY if role == "ocr" else frozenset())
            if record.provider != "ollama" or record.name not in allowed:
                raise ValueError(f"Small-model branch refuses {role}: {record.name!r}; no implicit model fallback")
    for role, tag in overrides.raw_tags.items():
        # A switched-off role never loads its tag, so a leftover DISCORD_MEMORY_*_MODEL line
        # must not stop the API booting. Switching the role back on removes it from
        # disabled_roles and this check refuses the tag at that boot.
        if role in overrides.disabled_roles:
            continue
        if tag not in ALLOWED | (OCR_ONLY if role == "ocr" else frozenset()):
            raise ValueError(f"Small-model branch refuses {role} override: {tag!r}")
