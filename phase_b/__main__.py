# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
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
"""Entry point: `python -m phase_b` boots uvicorn."""

import uvicorn

from phase_b.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run(
        "phase_b.server:app",
        host=s.host,
        port=s.port,
        log_level=s.log_level,
        reload=False,
        # WebSocket ping tuning — see phase_b.config.Settings for the
        # rationale. Default uvicorn 20/20 is too short for MiniMax-M3
        # reasoning_split (30-60s) which would otherwise tear down the
        # WS before the LLM reply_text / TTS frames reach the browser.
        ws_ping_interval=s.ws_ping_interval_s,
        ws_ping_timeout=s.ws_ping_timeout_s,
    )


if __name__ == "__main__":
    main()