# Legacy provider integrations

This directory preserves historical OpenAI, Ollama and llama.cpp provider-inference code and proof scripts for provenance only.

It is not part of the `memory_permanent` package, is not shipped in the canonical wheel, is not loaded by the runtime, and is not part of terminal conformance gates.

Canonical architecture: external AI/LLM systems are consumers of Memoria Permanente through governed REST/MCP/consumer integration boundaries. The memory core does not own or execute concrete LLM inference.
