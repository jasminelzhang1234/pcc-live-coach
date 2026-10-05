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
"""Step 7 smoke: barge-in flow.

Spin up a mock LLM (httpx MockTransport) + a slow mock TTS (mock WS server
that yields 5 PCM chunks 200ms apart). Then drive a real /ws/session
connection:
  1. start session, open WS
  2. wait for asr_ready
  3. send {"cmd":"speak"}
  4. after first TTS chunk arrives, send {"cmd":"barge_in"}
  5. assert: barge_in_stopped received, < 5 audio chunks received,
            no reply_end received
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# IMPORTANT: the server reads settings on first import, so patching must
# happen BEFORE the app/router are imported. Patch httpx at the package level
# by intercepting AsyncClient.post via a global transport swap in a
# mini-in-process server (see below).

# We'll run the actual FastAPI app via uvicorn in a subprocess for this test.
# Simpler: do an in-process TestClient with websockets, but FastAPI TestClient
# ws support is limited. Instead, hit the real server on port 8766 and
# override the LLM/TTS endpoints via env vars.
#
# Even simpler: skip the in-process LLM/TTS mocks — just verify that
# barge_in on a non-existent turn returns "warn", and that the parser
# accepts the cmd. Real barge-in needs live LLM/TTS; we test the cmd
# handling at the protocol level.
#
# We also need the LLM call to be slow enough that barge_in lands before
# reply_end. We mock LLM via monkey-patching the singleton chat() before
# the WS connect, by injecting a test-only entry in the server's settings
# is too invasive.
#
# Strategy: run the real phase_b server, but for THIS test use a special
# "barge-in test mode" where the server has been pre-configured to point
# LLM/TTS at local mocks via env vars. We pre-launch a local httpx mock
# server (not intercept transport) and a local TTS mock WS server, then
# point phase_b at them via MINIMAX_BASE_URL / TTS_WS_URL env vars.
# But uvicorn re-reads env at boot, so we need to start the server AFTER
# the mocks are up.
#
# Simpler still: write a focused unit test of the barge-in flow at the
# router level using FastAPI's TestClient, where we don't go through WS
# at all — we call the WS handler directly. But this still requires the
# LLM/TTS to be patchable.
#
# Cleanest: monkey-patch the LLM and TTS modules in the running server
# via a /api/test/override endpoint. That's too invasive for a smoke
# test.
#
# Pragmatic choice: spawn a separate phase_b server with env vars pointing
# at local mock LLM/TTS. We control the mocks' timing precisely.

import os
import subprocess
import signal


def _free_port() -> int:
    import socket as _s
    with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main() -> None:
    # ---- Spawn a controllable mock TTS WS server on a free port ----
    # Sends chunks as fast as possible (no artificial delay). This makes the
    # barge-in test independent of TTS timing — the only timing pressure is
    # the round-trip WS latency.
    PCM = b"\x00\x01" * 1600
    tts_chunks_sent = 0

    async def slow_tts(ws, path=None):
        nonlocal tts_chunks_sent
        try:
            await ws.recv()  # text request
            for _ in range(8):
                await ws.send(PCM)
                tts_chunks_sent += 1
                await asyncio.sleep(0.1)  # 100ms between chunks so barge-in can land mid-stream
            await ws.send(json.dumps({"event": "finished"}))
        except websockets.exceptions.ConnectionClosed:
            pass

    tts_server = await websockets.serve(slow_tts, "127.0.0.1", 0)
    tts_port = tts_server.sockets[0].getsockname()[1]
    tts_url = f"ws://127.0.0.1:{tts_port}"

    # ---- Mock LLM via stdlib asyncio HTTP ----
    LLM_BODY = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "我会一直说话,看你什么时候打断我。",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
    ).encode("utf-8")

    async def llm_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Naive HTTP/1.1 — read headers + body up to content-length, respond.
        try:
            data = await reader.read(64 * 1024)
            print(f"[llm-mock] got request, {len(data)} bytes", flush=True)
            sep = data.find(b"\r\n\r\n")
            if sep < 0:
                writer.close()
                return
            await asyncio.sleep(0.2)  # simulate LLM latency
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(LLM_BODY)).encode() + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n" + LLM_BODY
            )
            writer.write(response)
            await writer.drain()
            print("[llm-mock] sent reply", flush=True)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    llm_server = await asyncio.start_server(llm_handler, "127.0.0.1", 0)
    llm_port = llm_server.sockets[0].getsockname()[1]
    llm_url = f"http://127.0.0.1:{llm_port}/v1"

    # ---- Launch phase_b server with mocked LLM/TTS env vars ----
    env = os.environ.copy()
    env["LLM_BASE_URL"] = llm_url
    env["LLM_API_KEY"] = "test-key"
    env["TTS_WS_URL"] = tts_url
    env["TTS_API_KEY"] = "test-key"

    # Use a free port to avoid conflict with any running phase_b.
    server_port = _free_port()
    env["PCC_LIVE_PORT"] = str(server_port)
    proc = await asyncio.create_subprocess_exec(
        "python", "-m", "phase_b",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Background task: tee subprocess output to our stdout (start early so
    # boot + pre-warm logs are visible).
    async def _tee():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            print(f"[server] {line.decode('utf-8', errors='replace').rstrip()}", flush=True)
    tee_task = asyncio.create_task(_tee())

    # Wait for boot (up to 30s; first Aliyun NLS WS handshake on cold start can be slow)
    import httpx as _httpx
    last_err = None
    booted = False
    async with _httpx.AsyncClient() as boot_client:
        for _ in range(60):
            await asyncio.sleep(0.5)
            try:
                r = await boot_client.get(f"http://127.0.0.1:{server_port}/api/health", timeout=1.0)
                if r.status_code == 200:
                    booted = True
                    break
            except Exception as e:
                last_err = e
    if not booted:
        # dump whatever the server wrote
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                pass
        try:
            data = await asyncio.wait_for(proc.stdout.read(8192), timeout=2.0)
            print("---server output---")
            print(data.decode("utf-8", errors="replace"))
            print("---end---")
        except Exception:
            pass
        raise RuntimeError(f"server didn't start in 30s (returncode={proc.returncode}, last_err={last_err})")

    # Pre-warm the ASR model by opening and closing a WS session. This forces
    # the slow Aliyun NLS WS handshake (~10s on first run) to happen NOW
    # instead of during the barge-in timing window.
    print("[smoke] pre-warming ASR model (may take ~10s)…")
    async with _httpx.AsyncClient() as h:
        r = await h.post(f"http://127.0.0.1:{server_port}/api/session/start", json={"persona_id": "vec-01"})
        warm_sid = r.json()["id"]
    warm_url = f"ws://127.0.0.1:{server_port}/ws/session/{warm_sid}"
    async with websockets.connect(warm_url, ping_interval=None) as wws:
        # wait for asr_ready (up to 60s)
        warm_ok = False
        for i in range(60):
            try:
                msg = await asyncio.wait_for(wws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, (bytes, bytearray)):
                continue
            obj = json.loads(msg)
            print(f"[smoke] warm-up recv #{i}: {obj.get('event')}")
            if obj.get("event") == "asr_ready":
                warm_ok = True
                break
        if not warm_ok:
            print("[smoke] warm-up timed out, continuing anyway")
        else:
            print("[smoke] ASR pre-warm complete")
        # end warm session
        try:
            await wws.send(json.dumps({"cmd": "end"}))
            await asyncio.wait_for(wws.recv(), timeout=3.0)
        except Exception:
            pass

    try:
        # ---- Start session, open WS ----
        async with _httpx.AsyncClient() as h:
            r = await h.post(f"http://127.0.0.1:{server_port}/api/session/start", json={"persona_id": "vec-01"})
            sid = r.json()["id"]
        print(f"[smoke] session: {sid}")

        ws_url = f"ws://127.0.0.1:{server_port}/ws/session/{sid}"
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            # Drain "ready"
            await asyncio.wait_for(ws.recv(), timeout=3.0)
            # Skip asr_ready (not relevant here)

            # ---- Send speak with explicit text (skip ASR; we want a clean barge-in test) ----
            await ws.send(json.dumps({"cmd": "speak", "text": "请你详细说说你的困扰"}))
            print("[smoke] sent speak with text")

            # Single loop: wait for reply_text, then on first audio chunk send
            # barge_in, then wait for barge_in_stopped or reply_end. Total
            # budget 30s to absorb ASR cold-start on the same process.
            audio_chunks = 0
            reply_received = False
            t_bargein_sent = None
            t_bargein_ack = None
            got_reply_end = False
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(deadline - time.time(), 5.0))
                except asyncio.TimeoutError:
                    print(f"[smoke] recv timeout ({-int(time.time()-deadline)}s left)")
                    continue
                if isinstance(msg, (bytes, bytearray)):
                    audio_chunks += 1
                    if reply_received and t_bargein_sent is None:
                        await ws.send(json.dumps({"cmd": "barge_in"}))
                        t_bargein_sent = time.time()
                        print(f"[smoke] sent barge_in after {audio_chunks} chunks")
                else:
                    obj = json.loads(msg)
                    if obj.get("event") == "reply_text":
                        reply_received = True
                        print("[smoke] got reply_text, waiting for first audio chunk…")
                    elif obj.get("event") == "barge_in_stopped":
                        t_bargein_ack = time.time()
                        print(f"[smoke] got barge_in_stopped after {audio_chunks} chunks")
                        break
                    elif obj.get("event") == "reply_end":
                        got_reply_end = True
                        print("[smoke] got reply_end (should NOT happen after barge-in)")
                        break
                    elif obj.get("event") == "warn":
                        print(f"[smoke] warn: {obj.get('msg')}")

            assert reply_received, "never got reply_text within 30s"
            assert t_bargein_sent is not None, "never sent barge_in (no audio chunk arrived)"
            assert t_bargein_ack is not None, "never got barge_in_stopped"
            assert not got_reply_end, "reply_end should not fire after barge-in"
            assert audio_chunks < 8, f"too many chunks before stop: {audio_chunks} (expected < 8)"
            dt = (t_bargein_ack - t_bargein_sent) * 1000
            print(f"[smoke] barge-in latency (send→ack): {dt:.0f}ms")
            assert dt < 500, f"barge-in too slow: {dt}ms"
            print(f"[smoke] OK — barge-in stopped TTS after {audio_chunks} chunks (< 8 expected)")
    finally:
        tee_task.cancel()
        try:
            await tee_task
        except (asyncio.CancelledError, Exception):
            pass
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                proc.kill()
        tts_server.close()
        await tts_server.wait_closed()
        llm_server.close()
        await llm_server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())