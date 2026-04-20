#!/bin/sh
set -e

# Start Ollama server in background
ollama serve &
SERVE_PID=$!

# Wait until the REST API responds
echo "[ollama] Waiting for server to start..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama] Server ready."

# Pull models — these are no-ops if layers are already cached in ollama_data volume
echo "[ollama] Pulling nomic-embed-text..."
ollama pull nomic-embed-text

echo "[ollama] Pulling gemma3:4b..."
ollama pull gemma3:4b

echo "[ollama] All models ready."

# Hand control back to the server process
wait $SERVE_PID
