"""Public HTTPS surface: only the authenticated APK contract.

Run behind the tunnel: `uvicorn guardian.public:app --host 127.0.0.1 --port 8010`
Only `/healthz` and the `/v1` APK routes exist here; legacy telemetry, Agent,
WebSocket, docs and OpenAPI are not registered at all.
"""
from .factory import create_app

app = create_app(public_only=True)
