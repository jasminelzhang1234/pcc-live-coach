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
"""PCC tracker CSV append.

Step 9 — writes a new row to `progress/tracker-sessions.csv` for
each completed real-voice session. The 95-column header is read at
runtime from the existing CSV (so future column additions don't require
code changes). Marker scoring columns stay empty in v1; v2 will fill
them via the LLM-judge pcc-assessor.
"""

from __future__ import annotations
