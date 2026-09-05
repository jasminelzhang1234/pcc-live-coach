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
"""phase_b — PCC Live Coach (Phase B real-time voice web app).

Local-first practice tool for ICF PCC markers 5.5 / 6.6 / 7.6.
Audio stays on 127.0.0.1; LLM/TTS calls go to MiniMax (configurable).

License: Apache-2.0
"""

import logging

__version__ = "0.1.0"
__license__ = "Apache-2.0"

# Make sure phase_b.* loggers emit something even when funasr/torch haven't
# run logging.basicConfig() yet (we import those lazily). Idempotent.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )