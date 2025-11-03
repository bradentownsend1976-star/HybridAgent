import sys

sys.path.insert(0, r"/mnt/c/Users/brade/OneDrive/Desktop/HybridAgent")
from hybrid_agent.ollama_client import generate_diff, ollama_generate_diff

print("[OK] Import:", callable(ollama_generate_diff), callable(generate_diff))
