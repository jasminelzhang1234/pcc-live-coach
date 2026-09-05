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
"""PCC rhythm marker extractors.

Step 8: compute per-turn rhythm features from a recorded dialogue JSONL.
These numbers feed the dashboard (Step 10) and the v2 LLM-judge marker
scoring (out of scope for v1).
"""

from __future__ import annotations
