"""`python -m backend` starts the API server on http://localhost:8000."""
import uvicorn

from core import config as C

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=C.API_PORT)
