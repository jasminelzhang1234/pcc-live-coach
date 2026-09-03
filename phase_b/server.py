# Copyright 2026 the maintainer Zhang. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""FastAPI app factory.

Step 2 (revised): no lifespan — ASRWorker is per-session (Step 6 wires it).
Step 6 adds /ws/session that creates an ASRWorker per connection.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from phase_b.config import get_settings
from phase_b.wire.router import api_router, mount_static, mount_websocket


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="phase_b", version="0.1.0")

    # CORS: only allow the local host (refuse cross-origin browser requests).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://{s.host}:{s.port}"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    mount_static(app)
    mount_websocket(app)
    return app


app = create_app()