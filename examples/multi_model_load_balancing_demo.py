"""
This script demonstrates how to implement a client-side load balancer
for multiple LLM API endpoints with LightRAG. This is useful for scaling
the inference layer in a local or distributed environment.

The example does the following:
1. Creates a simple mock LLM server using FastAPI.
2. Starts multiple instances of the mock server on different ports in background threads.
3. Implements a round-robin load balancer by wrapping the LightRAG `llm_model_func`.
4. Instantiates LightRAG with this custom load-balancing function.
5. Makes several queries to demonstrate that requests are distributed across the mock servers.
"""

import asyncio
import uvicorn
import threading
import itertools
from contextlib import contextmanager
import time

from fastapi import FastAPI
from pydantic import BaseModel
from lightrag import LightRAG, QueryParam
from lightrag.components.model_client import OpenAIClient


# 1. Mock LLM Server
# This simulates an LLM API endpoint like one provided by Ollama or vLLM.
mock_app = FastAPI()

class MockLLMRequest(BaseModel):
    model: str
    prompt: str

@mock_app.post("/v1/chat/completions")
async def mock_llm_endpoint(request: MockLLMRequest, raw_request: dict):
    port = raw_request["scope"]["server"][1]
    print(f"[Mock Server on port {port}] Received request for model: {request.model}")
    response_text = f"Response from server on port {port}"
    # Simulate an OpenAI-compatible streaming response
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response_text,
            },
            "finish_reason": "stop"
        }]
    }

def run_server(host: str, port: int):
    """Function to run the Uvicorn server."""
    uvicorn.run(mock_app, host=host, port=port, log_level="warning")

@contextmanager
def running_mock_servers(servers_config):
    """Context manager to start and stop servers."""
    threads = []
    for host, port in servers_config:
        thread = threading.Thread(target=run_server, args=(host, port), daemon=True)
        thread.start()
        threads.append(thread)
        print(f"[Main] Started mock LLM server on http://{host}:{port}")

    # Give servers a moment to start up
    time.sleep(2)

    try:
        yield
    finally:
        print("\n[Main] Shutting down mock servers (this may take a moment)...")
        # Servers are daemon threads, so they will exit when the main thread exits.
        # In a real application, you'd have a more graceful shutdown mechanism.

# 2. Round-Robin Load Balancer
def create_round_robin_load_balancer(model_endpoints: list[str]):
    """
    Factory function that creates a load-balancing llm_model_func.
    """
    endpoint_cycle = itertools.cycle(model_endpoints)

    async def load_balanced_llm_func(model: str, prompt: str, **kwargs):
        """
        This function will be used by LightRAG. It selects an endpoint
        in a round-robin fashion and forwards the request.
        """
        # Select the next endpoint from the cycle
        endpoint = next(endpoint_cycle)
        print(f"\n[Load Balancer] Routing request to: {endpoint}")

        # We can use LightRAG's built-in OpenAIClient to make the call.
        # This assumes the target servers are OpenAI-compatible.
        client = OpenAIClient(base_url=endpoint)

        # The actual call to the model endpoint
        response = await client.call(model=model, messages=[{"role": "user", "content": prompt}], **kwargs)

        # Extract the content from the response
        return response.choices[0].message.content

    return load_balanced_llm_func

async def main():
    """
    Main function to run the demonstration.
    """
    # Configuration for our mock servers
    mock_servers_config = [
        ("127.0.0.1", 8001),
        ("127.0.0.1", 8002),
        ("127.0.0.1", 8003),
    ]
    model_endpoints = [f"http://{host}:{port}/v1" for host, port in mock_servers_config]

    with running_mock_servers(mock_servers_config):
        print("\n[Main] Mock servers are running. Initializing LightRAG with load balancer.")

        # 3. Instantiate LightRAG with the custom load balancer
        load_balancer_func = create_round_robin_load_balancer(model_endpoints)

        # We use a minimal LightRAG config for this example, as we only care about the LLM call.
        # We pass our load balancer as the `llm_model_func`.
        # Note: For this to work, we must specify a compatible `llm_binding` like 'openai',
        # but the actual function call is handled by our custom function.
        rag = LightRAG(
            llm_model_func=load_balancer_func,
            llm_model_name="gpt-4-mock", # The model name is passed to our function
        )

        # 4. Make several queries to demonstrate load balancing
        print("\n[Main] Making 5 queries to demonstrate round-robin load balancing...")
        for i in range(5):
            query = f"This is query number {i+1}"
            print(f"\n[Main] Sending query: '{query}'")

            # We use bypass mode to directly call the llm_model_func without RAG logic
            response = await rag.aquery(query, param=QueryParam(mode="bypass"))

            print(f"[Main] Received response: '{response}'")

            # Small delay to make the output readable
            time.sleep(1)

if __name__ == "__main__":
    # To run this example:
    # 1. Make sure you have `fastapi` and `uvicorn` installed:
    #    pip install fastapi "uvicorn[standard]"
    # 2. Run the script:
    #    python examples/multi_model_load_balancing_demo.py

    asyncio.run(main())
