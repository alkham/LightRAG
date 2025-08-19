# Agent Instructions and Explanations

This document contains explanations about the `lightrag-server` codebase and instructions for agents working on it.

---

## The Document Upload and Processing Pipeline

The process of uploading a document, parsing it, and adding its data to the database in `lightrag-server` follows a sophisticated, asynchronous pipeline. Here is a step-by-step breakdown.

### 1. Endpoint and File Handling
The process begins at the `/documents/upload` API endpoint. It receives the file, sanitizes the filename for security, and saves it to a designated input directory.

### 2. Asynchronous Task Initiation
To ensure responsiveness, the API immediately returns a `track_id` and hands off the processing to a background task (`pipeline_index_file`). This allows the server to handle multiple uploads concurrently.

### 3. Content Extraction and Parsing
The background task's `pipeline_enqueue_file` function inspects the file's extension to select the correct parsing logic. It can dynamically install required libraries (e.g., `pypdf2` for PDFs) and extracts the raw text content.

### 4. Document Enqueueing
The extracted text is passed to the `apipeline_enqueue_documents` method in the `LightRAG` class. This method assigns a unique ID, sets the document's status to `PENDING`, and stores the full text in a key-value store.

### 5. The Processing Pipeline (Core RAG Logic)
The `apipeline_process_enqueue_documents` method processes the queue. For each document, it performs:
*   **Chunking**: Divides the text into smaller, manageable chunks.
*   **Knowledge Extraction**: Uses a Large Language Model (LLM) to identify key entities and relationships within each chunk.
*   **Data Storage**: Persists the extracted information across multiple specialized storage systems:
    *   **Key-Value Store**: For text chunks.
    *   **Vector Databases**: For semantic search on chunks, entities, and relationships.
    *   **Graph Database**: To build the knowledge graph connecting entities and relationships to their source chunks.

### 6. Finalization and Status Update
Once all chunks are processed, the document's status is updated to `PROCESSED`. If an error occurs, it's marked as `FAILED`. The `_insert_done` method is then called to ensure all data is persisted to disk.

---

## Scaling the RAG Bot for Multiple Users (Local Environment)

This plan outlines a strategy for scaling the `lightrag-server` to support multiple concurrent users for both querying and document uploads in a local, air-gapped environment. The key is to move from the default single-process, file-based architecture to a robust, distributed system.

### High-Level Architecture
The proposed architecture decouples the application into four main layers, each independently scalable:
1.  **API Layer**: Handles user requests.
2.  **Processing Layer**: Manages intensive background tasks like document ingestion.
3.  **Storage Layer**: Provides persistent, concurrent data storage.
4.  **Inference Layer**: Serves the LLM for generation and extraction.

### Component-wise Scaling Strategy

#### 1. API Layer: Stateless and Load-Balanced
*   **Action**: Run multiple instances of the FastAPI web server. Since the application logic is mostly stateless (state is handled by the storage layer), it can be scaled horizontally.
*   **Technology**: Use a load balancer like **Nginx** to distribute incoming HTTP requests across the server instances. This increases throughput and availability.
*   **Benefit**: Handles a higher volume of concurrent user queries and upload requests without overwhelming a single server process.

#### 2. Processing Layer: Decoupled Background Workers
*   **Action**: Move the document processing pipeline out of the API server process into a dedicated pool of background workers.
*   **Technology**: Implement a task queue system. A standard choice is **Celery** with a **Redis** message broker.
    *   When a file is uploaded, the API server's only job is to create a "process document" task and push it to the Redis queue.
    *   A separate pool of Celery workers, running on different machines or cores, will listen for tasks on the queue, execute the processing pipeline, and update the databases.
*   **Benefit**: Isolates the CPU/GPU-intensive ingestion process from the user-facing API, preventing slowdowns and timeouts during uploads. Allows for independent scaling of processing power based on ingestion load.

#### 3. Storage Layer: Production-Grade Databases
*   **Action**: Replace the default file-based storage backends (`JsonKVStorage`, `NanoVectorDBStorage`, `NetworkXStorage`) with production-grade databases that support concurrent access.
*   **Technology**:
    *   **Vector Database**: Replace `NanoVectorDBStorage` with a client-server vector database like **Qdrant**, **Weaviate**, or **Milvus**. These are designed for high-performance similarity search and concurrent operations.
    *   **Graph Database**: Replace `NetworkXStorage` with a persistent graph database like **Neo4j** or **Memgraph**. These provide transactional guarantees and are built for multi-user environments.
    *   **KV/Document/Status Store**: Replace `JsonKVStorage` and `JsonDocStatusStorage` with a more robust solution. **Redis** can be used for caching and simple key-value data. A NoSQL database like **MongoDB** or a relational database like **PostgreSQL** can handle document content, status tracking, and metadata with better concurrency and query capabilities.
*   **Benefit**: Eliminates file-locking bottlenecks, ensures data consistency with transactions, and allows multiple parts of the system to read and write data simultaneously without corruption.

#### 4. Inference Layer: Centralized LLM Serving
*   **Action**: Avoid loading the LLM into memory in multiple API or worker processes. Instead, create a centralized, dedicated service for LLM inference.
*   **Technology**: Use a specialized inference server like **Ollama**, **vLLM**, or **NVIDIA Triton Inference Server**.
    *   This server runs on dedicated hardware (ideally with powerful GPUs) and exposes the LLM via a local network API endpoint.
    *   The API servers (for queries) and Celery workers (for knowledge extraction) would make simple HTTP requests to this service.
*   **Benefit**: Optimizes expensive GPU resource usage. Allows for model-specific optimizations (like continuous batching in vLLM) to maximize throughput and serve multiple requests concurrently.

### Deployment Strategy (Local Environment)
*   **Action**: Use containerization to manage and orchestrate all the distributed services.
*   **Technology**:
    *   **Docker Compose**: Ideal for a single-host deployment. A `docker-compose.yml` file can define and link all the services: the Nginx load balancer, multiple FastAPI app containers, Redis, the chosen databases (Qdrant, Neo4j, etc.), the Celery worker containers, and the LLM inference server.
    *   **Kubernetes**: For multi-host deployments or more complex orchestration needs, a lightweight Kubernetes distribution like **k3s** or **minikube** can be used. The existing `k8s-deploy` directory in the repository suggests this is a considered deployment path.
*   **Benefit**: Simplifies setup, ensures consistent environments, and makes managing the lifecycle of the various components (starting, stopping, updating) straightforward.

### Summary Flow of a Scaled Document Upload
1.  User sends a file to the **Nginx** load balancer.
2.  Nginx forwards the request to one of the **FastAPI server** instances.
3.  The FastAPI server saves the file to a shared network storage location and pushes a task with the file's path to the **Redis** queue. It immediately returns a `track_id` to the user.
4.  A **Celery worker** picks up the task from the queue.
5.  The worker reads the file, extracts text, and for each chunk, calls the **LLM Inference Server** to extract knowledge.
6.  The worker writes the chunks, embeddings, entities, and relationships to the **Qdrant**, **Neo4j**, and **MongoDB/PostgreSQL** databases.
7.  The worker updates the document's status in the database to `PROCESSED`.
