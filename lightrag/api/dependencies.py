import asyncio
from typing import Dict
from functools import lru_cache

from fastapi import Depends

from lightrag import LightRAG
from lightrag.api.routers.document_routes import DocumentManager
from lightrag.api.utils_api import get_combined_auth_dependency
from .config import global_args

# Caching for LightRAG and DocumentManager instances
# We use a simple dictionary as an in-memory cache.
# The key will be the workspace name (str).
rag_instances: Dict[str, LightRAG] = {}
doc_manager_instances: Dict[str, DocumentManager] = {}
instance_lock = asyncio.Lock()


def get_lightrag_instance_params(workspace: str) -> dict:
    """Constructs the parameters for LightRAG initialization."""
    # Most parameters are taken from the global arguments.
    # The workspace parameter is dynamically set.
    from lightrag.utils import EmbeddingFunc
    from lightrag.llm.ollama import ollama_model_complete, ollama_embed
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.llm.azure_openai import azure_openai_complete_if_cache, azure_openai_embed
    from lightrag.llm.bedrock import bedrock_complete_if_cache, bedrock_embed
    from lightrag.llm.lollms import lollms_model_complete, lollms_embed
    from lightrag.llm.jina import jina_embed
    from lightrag.llm.binding_options import OllamaLLMOptions, OllamaEmbeddingOptions, OpenAILLMOptions
    from lightrag.types import GPTKeywordExtractionFormat

    args = global_args
    # This logic is duplicated from lightrag_server.py to avoid circular imports.
    # In a larger refactoring, this could be further centralized.

    # Embedding function setup
    embedding_func = EmbeddingFunc(
        embedding_dim=args.embedding_dim,
        func=lambda texts: (
            lollms_embed(texts, embed_model=args.embedding_model, host=args.embedding_binding_host, api_key=args.embedding_binding_api_key)
            if args.embedding_binding == "lollms"
            else (
                ollama_embed(texts, embed_model=args.embedding_model, host=args.embedding_binding_host, api_key=args.embedding_binding_api_key, options=OllamaEmbeddingOptions.options_dict(args))
                if args.embedding_binding == "ollama"
                else (
                    azure_openai_embed(texts, model=args.embedding_model, api_key=args.embedding_binding_api_key)
                    if args.embedding_binding == "azure_openai"
                    else (
                        bedrock_embed(texts, model=args.embedding_model)
                        if args.embedding_binding == "aws_bedrock"
                        else (
                            jina_embed(texts, dimensions=args.embedding_dim, base_url=args.embedding_binding_host, api_key=args.embedding_binding_api_key)
                            if args.embedding_binding == "jina"
                            else openai_embed(texts, model=args.embedding_model, base_url=args.embedding_binding_host, api_key=args.embedding_binding_api_key)
                        )
                    )
                )
            )
        ),
    )

    # LLM function setup
    async def openai_alike_model_complete(prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs):
        if keyword_extraction: kwargs["response_format"] = GPTKeywordExtractionFormat
        if history_messages is None: history_messages = []
        if args.llm_binding == "openai":
            kwargs.update(OpenAILLMOptions.options_dict(args))
        else:
            kwargs["temperature"] = args.temperature
        return await openai_complete_if_cache(args.llm_model, prompt, system_prompt=system_prompt, history_messages=history_messages, base_url=args.llm_binding_host, api_key=args.llm_binding_api_key, **kwargs)

    async def azure_openai_model_complete_func(prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs):
        if keyword_extraction: kwargs["response_format"] = GPTKeywordExtractionFormat
        if history_messages is None: history_messages = []
        if args.llm_binding == "azure_openai":
            kwargs.update(OpenAILLMOptions.options_dict(args))
        else:
            kwargs["temperature"] = args.temperature
        return await azure_openai_complete_if_cache(args.llm_model, prompt, system_prompt=system_prompt, history_messages=history_messages, base_url=args.llm_binding_host, api_key=global_args.llm_binding_api_key, api_version=global_args.azure_openai_api_version, **kwargs)

    async def bedrock_model_complete_func(prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs):
        if keyword_extraction: kwargs["response_format"] = GPTKeywordExtractionFormat
        if history_messages is None: history_messages = []
        kwargs["temperature"] = args.temperature
        return await bedrock_complete_if_cache(args.llm_model, prompt, system_prompt=system_prompt, history_messages=history_messages, **kwargs)

    llm_model_func = (
        lollms_model_complete if args.llm_binding == "lollms"
        else ollama_model_complete if args.llm_binding == "ollama"
        else bedrock_model_complete_func if args.llm_binding == "aws_bedrock"
        else azure_openai_model_complete_func if args.llm_binding == "azure_openai"
        else openai_alike_model_complete
    )

    llm_model_kwargs = (
        {"host": args.llm_binding_host, "timeout": args.timeout, "options": OllamaLLMOptions.options_dict(args), "api_key": args.llm_binding_api_key}
        if args.llm_binding in ["lollms", "ollama"]
        else {"timeout": args.timeout} if args.llm_binding == "azure_openai" else {}
    )

    return {
        "working_dir": args.working_dir,
        "workspace": workspace,
        "llm_model_func": llm_model_func,
        "llm_model_name": args.llm_model,
        "llm_model_max_async": args.max_async,
        "summary_max_tokens": args.max_tokens,
        "chunk_token_size": int(args.chunk_size),
        "chunk_overlap_token_size": int(args.chunk_overlap_size),
        "llm_model_kwargs": llm_model_kwargs,
        "embedding_func": embedding_func,
        "kv_storage": args.kv_storage,
        "graph_storage": args.graph_storage,
        "vector_storage": args.vector_storage,
        "doc_status_storage": args.doc_status_storage,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": args.cosine_threshold},
        "enable_llm_cache_for_entity_extract": args.enable_llm_cache_for_extract,
        "enable_llm_cache": args.enable_llm_cache,
        "max_parallel_insert": args.max_parallel_insert,
        "max_graph_nodes": args.max_graph_nodes,
        "addon_params": {"language": args.summary_language},
    }


async def get_rag_instance(
    user_payload: dict = Depends(get_combined_auth_dependency(global_args.key))
) -> LightRAG:
    """
    A dependency that provides a LightRAG instance based on the user's workspace.
    It caches instances to avoid re-creation on every request.
    """
    workspace = user_payload.get("workspace")
    if not workspace:
        # This should not happen if combined_auth_dependency is working correctly
        raise ValueError("Workspace could not be determined from user token.")

    async with instance_lock:
        if workspace not in rag_instances:
            # Instance does not exist, create and cache it
            params = get_lightrag_instance_params(workspace)
            rag_instance = LightRAG(**params)
            # Initialize storage for the new instance
            await rag_instance.initialize_storages()
            rag_instances[workspace] = rag_instance

        return rag_instances[workspace]


async def get_doc_manager_instance(
    user_payload: dict = Depends(get_combined_auth_dependency(global_args.key))
) -> DocumentManager:
    """
    A dependency that provides a DocumentManager instance based on the user's workspace.
    It caches instances to avoid re-creation on every request.
    """
    workspace = user_payload.get("workspace")
    if not workspace:
        raise ValueError("Workspace could not be determined from user token.")

    async with instance_lock:
        if workspace not in doc_manager_instances:
            # Create and cache a new DocumentManager instance
            doc_manager_instances[workspace] = DocumentManager(
                global_args.input_dir, workspace=workspace
            )
        return doc_manager_instances[workspace]
