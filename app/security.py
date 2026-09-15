from fastapi import Request
from fastapi.responses import JSONResponse

class SecretPathMiddleware:
    def __init__(self, app, secret: str):
        self.app = app
        self.prefix = f"/{secret}"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            # If accessing prefix without trailing slash, redirect to trailing slash
            # so relative paths in HTML (like style.css, app.js) resolve correctly
            if path == self.prefix:
                query_string = scope.get("query_string", b"").decode("latin-1")
                redirect_url = f"{self.prefix}/" + (f"?{query_string}" if query_string else "")
                response = JSONResponse(
                    status_code=307,
                    headers={"Location": redirect_url},
                    content={"detail": "Redirecting"}
                )
                await response(scope, receive, send)
                return

            if not path.startswith(f"{self.prefix}/"):
                response = JSONResponse(status_code=404, content={"detail": "Not Found"})
                await response(scope, receive, send)
                return
            # Remove the secret prefix so routing works normally
            scope["path"] = path[len(self.prefix):] or "/"
        await self.app(scope, receive, send)
