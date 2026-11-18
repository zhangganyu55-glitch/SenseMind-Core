"""Local app: `uvicorn guardian.main:app`."""
from .factory import create_app

app = create_app()
