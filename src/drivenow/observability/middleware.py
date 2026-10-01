"""Request timing middleware feeding ``drivenow_request_duration_seconds``."""

from __future__ import annotations

from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from drivenow.observability.metrics import AppMetrics

# Monitoring endpoints don't count toward response times (Decisions 8 and 14).
EXCLUDED_PATHS = frozenset({"/metrics", "/stats", "/health"})
UNMATCHED_ROUTE = "<unmatched>"


class RequestMetricsMiddleware:
    """Times each HTTP request and labels it with the route template, not the raw path."""

    def __init__(self, app: ASGIApp, metrics: AppMetrics, excluded_paths: frozenset[str] = EXCLUDED_PATHS) -> None:
        self.app = app
        self.metrics = metrics
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        status_code = 500  # if the app raises before responding, the outer handler sends a 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        start = perf_counter()
        try:
            await self.app(scope, receive, send_with_status)
        finally:
            # The router stores the matched route in the scope, e.g. "/cars/{car_id}".
            route = getattr(scope.get("route"), "path", None) or UNMATCHED_ROUTE
            self.metrics.observe_request(scope["method"], route, status_code, perf_counter() - start)
