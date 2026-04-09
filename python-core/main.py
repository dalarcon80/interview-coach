"""
Interview Coach - Main Entry Point
FastAPI application with WebSocket support
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from api.server import app

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run(
        "api.server:app",
        host="127.0.0.1",
        port=port,
        reload=True,
    )
