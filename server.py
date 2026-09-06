"""Entry point: python server.py -> http://localhost:4173"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from app import app  # noqa: E402

if __name__ == "__main__":
    print("NEXUS running at http://localhost:4173")
    app.run(host="0.0.0.0", port=4173, debug=False)
