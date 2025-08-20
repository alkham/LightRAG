from celery import Celery
import asyncio
from pathlib import Path

# It's crucial that the celery app is defined at the top level of a module.
celery_app = Celery(
    "lightrag_tasks",
    broker="redis://localhost:6379/0",  # Default Redis broker
    backend="redis://localhost:6379/0", # Default Redis backend for results
    include=["lightrag.api.celery_app"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="process_document_task")
def process_document_task(workspace: str, file_path_str: str, track_id: str):
    """
    Celery task to process a single document.
    This function will run in a separate Celery worker process.
    """
    from lightrag.api.dependencies import get_lightrag_instance_params
    from lightrag.api.routers.document_routes import (
        DocumentManager,
        pipeline_index_file,
    )
    from lightrag import LightRAG

    # Since this runs in a separate process, we need to create
    # our own instances of LightRAG and DocumentManager.

    # Create a DocumentManager for the specific workspace
    # Note: We need access to the base input_dir from global_args
    from lightrag.api.config import global_args
    doc_manager = DocumentManager(global_args.input_dir, workspace=workspace)

    # Create a LightRAG instance for the specific workspace
    rag_params = get_lightrag_instance_params(workspace)
    rag_instance = LightRAG(**rag_params)

    file_path = Path(file_path_str)

    # The original pipeline_index_file is async, so we need to run it in an event loop.
    # Celery 4.x supports asyncio, but it can be tricky. A simple way is to
    # create a new event loop for the task.
    async def run_processing():
        await rag_instance.initialize_storages()
        try:
            # We call the core processing logic.
            await pipeline_index_file(rag_instance, file_path, track_id=track_id)
        finally:
            await rag_instance.finalize_storages()

    # Run the async function to completion.
    # This is a blocking call within the worker, which is the desired behavior.
    asyncio.run(run_processing())

    return f"Successfully processed {file_path.name} in workspace {workspace} with track_id {track_id}"
