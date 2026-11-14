"""Convenience runner script for the EHR Media Intelligence Platform."""

import uvicorn
from src.config import settings

if __name__ == "__main__":
    print(f"Starting EHR Media Intelligence Server at http://{settings.HOST}:{settings.PORT}")
    uvicorn.run("src.api.app:app", host=settings.HOST, port=settings.PORT, reload=True)

