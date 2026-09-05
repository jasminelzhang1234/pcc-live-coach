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
"""Step 2 smoke: feed sample-60s.wav through ASRWorker, verify events emit."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

# Make phase_b importable when run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.asr.asr_worker import ASRWorker  # noqa: E402


SAMPLE = PROJECT_ROOT / "tests" / "fixtures" / "sample-60s.wav"


async def main() -> None:
    assert SAMPLE.is_file(), f"missing fixture: {SAMPLE}"
    audio, sr = sf.read(str(SAMPLE), dtype="int16")
    assert sr == 16000, f"expected 16kHz, got {sr}"
    pcm = audio.tobytes()

    chunk_ms = 1000
    bytes_per_chunk = 16000 * 2 * chunk_ms // 1000  # int16 mono

    worker = ASRWorker(model="iic/SenseVoiceSmall", chunk_ms=chunk_ms)
    print("[smoke] starting worker (model load ~5s) ...")
    await worker.start()
    print("[smoke] worker started")

    # Feed the fixture in 1s slices (matches chunk_ms).
    n_chunks = len(pcm) // bytes_per_chunk
    print(f"[smoke] feeding {n_chunks} x {chunk_ms}ms chunks ({len(pcm)/16000/2:.1f}s total)")

    feed_task = asyncio.create_task(_feed(worker, pcm, bytes_per_chunk, chunk_ms))

    event_count = 0
    t_start = asyncio.get_running_loop().time()
    async for ev in worker.events():
        elapsed = asyncio.get_running_loop().time() - t_start
        event_count += 1
        print(f"[+{elapsed:5.1f}s] event: {ev}")
        if elapsed > (n_chunks * chunk_ms / 1000 + 3):
            break
        if event_count >= 12:
            break

    await feed_task
    await worker.stop()
    print(f"[smoke] OK — received {event_count} events")


async def _feed(worker, pcm: bytes, chunk_bytes: int, chunk_ms: int) -> None:
    n = len(pcm) // chunk_bytes
    for i in range(n):
        worker.feed(pcm[i * chunk_bytes : (i + 1) * chunk_bytes])
        await asyncio.sleep(chunk_ms / 1000.0)


if __name__ == "__main__":
    asyncio.run(main())