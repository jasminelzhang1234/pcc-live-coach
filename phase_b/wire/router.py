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
"""Static file serving + REST routes + WebSocket.

REST endpoints:
  /api/personas                GET   list persona IDs
  /api/personas/{id}           GET   full persona
  /api/health                  GET   liveness
  /api/session/start           POST  start a session
  /api/session/{id}            GET   session metadata
  /api/session/{id}/audio      POST  push raw PCM (legacy / fallback)
  /api/session/{id}/end        POST  finalize session

WebSocket:
  /ws/session/{id}             full pipeline: browser audio ⇄ ASR ⇄ LLM ⇄ TTS

WS protocol (browser ↔ server):
  browser → server:
    binary frame          : int16 mono 16kHz PCM (continuous while mic open)
    {"cmd": "speak"}      : commit current accumulated transcript → run_turn()
    {"cmd": "barge_in"}   : interrupt the active turn (cancel run_turn, stop TTS)
    {"cmd": "end"}        : finalize session
    {"cmd": "ping"}       : keepalive (server replies {"event":"pong"})
  server → browser:
    {"event":"partial",   : ASR partial text every ~1s
        "text", "audio_ms", "latency_ms"}
    {"event":"reply_text",: coach reply text (for transcript display)
        "text", "session_id"}
    binary frame          : TTS PCM chunks (browser plays via WebAudio)
    {"event":"reply_end"} : TTS finished, ready for next "speak"
    {"event":"barge_in_stopped", "turn"} : reply interrupted, ready for next "speak"
    {"event":"ended"}     : session ended (response to "end")
    {"event":"error",     : pipeline failure
        "stage", "error"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from phase_b.asr.asr_worker import ASRWorker
from phase_b.coach.orchestrator import run_turn
from phase_b.personas.loader import list_ids, load as load_persona
from phase_b.session.manager import get_manager


logger = logging.getLogger(__name__)


_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


api_router = APIRouter(prefix="/api")


_H1_RE = re.compile(r"^#\s+(.+?)$", re.MULTILINE)


def _extract_name(persona: dict) -> str:
    """Pull the H1 title from a parsed persona's preamble section."""
    raw = (persona.get("sections") or {}).get("_title", "") or ""
    m = _H1_RE.search(raw)
    return m.group(1).strip() if m else persona.get("id", "")


class SessionStartBody(BaseModel):
    persona_id: str
    topic: Optional[str] = ""
    difficulty: int = 0


@api_router.get("/personas", response_model=List[dict])
def get_personas() -> List[dict]:
    out: List[dict] = []
    for pid in list_ids():
        try:
            p = load_persona(pid)
        except FileNotFoundError:
            continue
        out.append({
            "id": p.get("id", pid),
            "name": _extract_name(p),
            "line": p.get("line", ""),
            "difficulty": p.get("difficulty", 0),
        })
    return out


@api_router.get("/personas/{persona_id}")
def get_persona(persona_id: str) -> dict:
    try:
        return load_persona(persona_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api_router.get("/health")
def health() -> dict:
    return {"status": "ok", "phase_b_version": "0.1.0"}


@api_router.post("/session/start")
def session_start(body: SessionStartBody) -> dict:
    try:
        load_persona(body.persona_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    mgr = get_manager()
    state = mgr.start(
        persona_id=body.persona_id,
        topic=body.topic or "",
        difficulty=body.difficulty,
    )
    return state.to_dict()


@api_router.get("/session/{session_id}")
def session_get(session_id: str) -> dict:
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return state.to_dict()


@api_router.post("/session/{session_id}/audio", include_in_schema=False)
async def session_audio(session_id: str, request: Request) -> dict:
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    body = await request.body()
    if not body:
        return {"bytes_written": 0}
    state.recorder.write_audio(body)
    return {"bytes_written": len(body), "audio_ms": state.recorder.audio_duration_ms()}


@api_router.post("/session/{session_id}/end")
def session_end(session_id: str) -> dict:
    state = get_manager().end(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return state.to_dict()


@api_router.get("/session/{session_id}/rhythm")
def session_rhythm(session_id: str) -> dict:
    """Return the per-turn rhythm features for a session.

    Reads `sessions/rhythm/<id>.jsonl` (written by manager.end() → rhythm
    extraction). Returns {"turns": [...]} or 404 if the rhythm file
    hasn't been written yet (e.g. session still in progress or older
    session that predates Step 8).
    """
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    rhythm_path = Path(state.recorder.rhythm_path)
    if not rhythm_path.is_file():
        raise HTTPException(status_code=404, detail=f"rhythm not yet available: {session_id}")
    turns = []
    with open(rhythm_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {
        "session_id": session_id,
        "turns": turns,
        "kpis": _compute_kpis(turns),
    }


def _compute_kpis(turns: List[dict]) -> dict:
    """Aggregate per-turn features into dashboard KPI tiles."""
    if not turns:
        return {"mean_cpm": 0, "silence_5_5_count": 0, "barge_in_count": 0, "turn_count": 0}
    mean_cpm = sum(t.get("cpm", 0) for t in turns) / len(turns)
    silence_5_5_count = sum(1 for t in turns if t.get("silence_5_5"))
    barge_in_count = sum(int(t.get("barge_in_count", 0)) for t in turns)
    return {
        "mean_cpm": int(mean_cpm),
        "silence_5_5_count": silence_5_5_count,
        "barge_in_count": barge_in_count,
        "turn_count": len(turns),
    }


def mount_static(app) -> None:
    """Mount `phase_b/static/*` at `/` (SPA-style index.html)."""
    if not _STATIC_DIR.is_dir():
        raise RuntimeError(f"static dir not found: {_STATIC_DIR}")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(
            _STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )


# ---------------------------------------------------------------------------
# WebSocket: full voice pipeline
# ---------------------------------------------------------------------------


async def _ws_session_impl(websocket: WebSocket, session_id: str) -> None:
    """Run the ASR ↔ LLM ↔ TTS pipeline for one session."""
    logger.info("[ws %s] connecting", session_id)
    await websocket.accept()
    logger.info("[ws %s] accepted", session_id)
    mgr = get_manager()
    state = mgr.get(session_id)
    if state is None:
        await websocket.send_json({"event": "error", "stage": "ws", "error": f"session not found: {session_id}"})
        await websocket.close(code=1008, reason="session not found")
        return
    logger.info("[ws %s] state ok, persona=%s", session_id, state.persona_id)

    # Per-connection ASR worker (one buffer = one user).
    from phase_b.config import get_settings

    s = get_settings()
    worker = ASRWorker(
        model=s.asr_model,
        sample_rate=16000,
        chunk_ms=s.asr_chunk_ms,
        language=s.asr_language,
    )
    # Send "ready" FIRST, before any background tasks. There's a known
    # Starlette quirk where websocket.send_json blocks until outstanding
    # tasks on the same WS finish a handshake; spawning tasks before
    # the first send can stall the first message for tens of seconds.
    await websocket.send_json({"event": "ready", "session_id": session_id, "persona_id": state.persona_id})
    logger.info("[ws %s] sent ready", session_id)

    # Now kick off model load in the background. feed() no-ops until model
    # is ready, so the first ~3s of audio (cold start) is silently dropped —
    # acceptable since the user usually waits a few seconds before speaking.
    load_task = asyncio.create_task(worker.start(), name=f"asr-load-{session_id}")

    last_text = ""  # sentinel; replaced by last_text_holder[0] updates from pump_asr
    # The actual live value lives in last_text_holder[0] below (mutable so the
    # pump_asr task can write it without `nonlocal`). Keep the legacy name
    # here for diff-friendliness vs. the previous version.
    turn_count = 0
    closed_normally = False
    closing = False
    barge_in_count = 0
    active_turn_task: Optional[asyncio.Task] = None  # running run_turn() — cancellable on barge-in
    last_text_holder = [""]  # most recent ASR partial text (mirrored from pump_asr)
    last_auto_submit_key = [None]
    audio_diag_bytes = [0]  # rolling byte counter for the audio-level diagnostic log

    async def cancel_task(task: Optional[asyncio.Task]) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def cancel_active_turn() -> bool:
        nonlocal active_turn_task
        task = active_turn_task
        if task is None:
            return False
        was_active = not task.done()
        await cancel_task(task)
        if active_turn_task is task:
            active_turn_task = None
        return was_active

    def utterance_identity(event: dict) -> tuple:
        return tuple(event.get(field) for field in ("text", "audio_ms", "is_final", "is_utterance_end"))

    async def submit_turn(text: str, auto_event=None) -> bool:
        nonlocal active_turn_task, turn_count
        if closing:
            return False
        text = (text or "").strip()
        if not text:
            await websocket.send_json({"event": "warn", "msg": "empty transcript; nothing to commit"})
            return False
        if active_turn_task is not None and not active_turn_task.done():
            await websocket.send_json({"event": "warn", "msg": "turn already in progress"})
            return False
        if auto_event is not None:
            auto_event_key = utterance_identity(auto_event)
            if last_auto_submit_key[0] == auto_event_key:
                return False
            last_auto_submit_key[0] = auto_event_key

        turn_count += 1
        turn_started_ms = int(time.time() * 1000)
        worker.clear_buffer()
        last_text_holder[0] = ""
        state.recorder.write_dialogue(
            {
                "role": "coach",
                "event": "utterance",
                "turn": turn_count,
                "text": text,
                "ms": turn_started_ms,
            }
        )

        async def run_one_turn(t=text, n=turn_count, t0=turn_started_ms):
            nonlocal active_turn_task
            try:
                async for ev in run_turn(
                    session_id=session_id,
                    persona_id=state.persona_id,
                    client_text=t,
                    user_difficulty=state.difficulty,
                ):
                    if closing:
                        return
                    if isinstance(ev, dict):
                        kind = ev.get("kind")
                        if kind == "reply_text":
                            await websocket.send_json(
                                {"event": "reply_text", "text": ev.get("text", ""), "turn": n}
                            )
                            state.recorder.write_dialogue(
                                {
                                    "role": "client",
                                    "event": "utterance",
                                    "turn": n,
                                    "text": ev.get("text", ""),
                                    "ms": int(time.time() * 1000),
                                }
                            )
                        elif kind == "reply_end":
                            await websocket.send_json({"event": "reply_end", "turn": n})
                            state.last_latency_ms = int(time.time() * 1000) - t0
                        elif kind == "error":
                            await websocket.send_json(
                                {"event": "error", "stage": ev.get("stage"), "error": ev.get("error")}
                            )
                    else:
                        try:
                            await websocket.send_bytes(ev)
                        except Exception:
                            logger.warning("ws send (audio) failed; aborting turn")
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("run_turn failed")
                try:
                    await websocket.send_json({"event": "error", "stage": "turn", "error": str(e)})
                except Exception:
                    pass
            finally:
                if active_turn_task is asyncio.current_task():
                    active_turn_task = None

        active_turn_task = asyncio.create_task(run_one_turn(), name=f"turn-{session_id}-{turn_count}")
        return True

    async def pump_asr() -> None:
        """Forward ASRWorker events to the browser as JSON, and mirror the
        latest partial text into ``last_text_holder`` so the speak handler can
        read it without racing the partial pump."""
        try:
            async for ev in worker.events():
                if closing:
                    return
                if ev.get("event") == "partial":
                    last_text_holder[0] = ev.get("text", "") or ""
                try:
                    await websocket.send_json(ev)
                except Exception:
                    return
                if closing:
                    return
                if (
                    ev.get("event") == "partial"
                    and ev.get("is_utterance_end") is True
                    and (ev.get("text") or "").strip()
                ):
                    await submit_turn(
                        ev.get("text", ""),
                        auto_event=ev,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pump_asr failed")

    pump_task = asyncio.create_task(pump_asr(), name=f"asr-pump-{session_id}")
    # Notify browser once the ASR model is loaded (first "partial" implicitly
    # signals readiness; we send a dedicated event so the UI can update status).
    async def _notify_when_loaded():
        try:
            await load_task
            if closing:
                return
            await websocket.send_json({"event": "asr_ready"})
        except Exception as e:
            logger.warning("asr load failed in background: %s", e)
            try:
                await websocket.send_json({"event": "error", "stage": "asr_load", "error": str(e)})
            except Exception:
                pass

    notify_task = asyncio.create_task(_notify_when_loaded(), name=f"asr-notify-{session_id}")

    try:
        # (ready already sent before background tasks were created)
        pass

        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break

            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("type") == "websocket.receive":
                # Binary = PCM
                if "bytes" in msg and msg["bytes"] is not None:
                    pcm = msg["bytes"]
                    if pcm:
                        worker.feed(pcm)
                        try:
                            state.recorder.write_audio(pcm)
                        except Exception:
                            logger.exception("recorder.write_audio failed")
                        # Diagnostic: log RMS + byte count once per second so we can
                        # tell whether the browser is sending silent frames, quiet
                        # audio, or real speech. Helps when partials come out as
                        # garbage ("嗯"/"which"/"a girl is drinking coffee") — that
                        # pattern means the server is processing audio but the
                        # audio contains no real speech.
                        audio_diag_bytes[0] += len(pcm)
                        if audio_diag_bytes[0] >= 16000 * 2:  # ~1s of 16kHz int16 mono
                            import numpy as _np
                            samples = _np.frombuffer(pcm, dtype=_np.int16).astype(_np.float32)
                            rms = float(_np.sqrt(_np.mean(samples ** 2))) if len(samples) else 0.0
                            peak = float(_np.max(_np.abs(samples))) if len(samples) else 0.0
                            logger.info(
                                "[%s] audio-diag: %d B/s, rms=%.1f peak=%.1f (int16 units)",
                                session_id, audio_diag_bytes[0], rms, peak,
                            )
                            audio_diag_bytes[0] = 0
                    continue
                # Text = JSON control
                if "text" in msg and msg["text"] is not None:
                    try:
                        obj = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        await websocket.send_json({"event": "error", "stage": "decode", "error": "bad json"})
                        continue
                    cmd = obj.get("cmd")
                    if cmd == "ping":
                        await websocket.send_json({"event": "pong", "ts": int(time.time() * 1000)})
                    elif cmd == "speak":
                        # "speak" can be sent with an explicit text override
                        # ({"cmd":"speak","text":"..."}) — handy for tests and
                        # for manual paste-in mode. Without override, the most
                        # recent ASR partial (mirrored by pump_asr) is used.
                        text = (obj.get("text") or "").strip() or last_text_holder[0].strip()
                        await submit_turn(text)
                    elif cmd == "barge_in":
                        if active_turn_task is not None and not active_turn_task.done():
                            await cancel_active_turn()
                            barge_in_count += 1
                            worker.clear_buffer()
                            state.recorder.write_dialogue(
                                {
                                    "role": "_meta",
                                    "event": "barge_in",
                                    "turn": turn_count,
                                    "ms": int(time.time() * 1000),
                                }
                            )
                            last_text_holder[0] = ""  # discard stale partial from before barge
                            try:
                                await websocket.send_json({"event": "barge_in_stopped", "turn": turn_count})
                            except Exception:
                                pass
                            logger.info("[%s] barge-in turn=%d total=%d", session_id, turn_count, barge_in_count)
                        else:
                            await websocket.send_json({"event": "warn", "msg": "no active turn to barge"})
                    elif cmd == "end":
                        closing = True
                        await cancel_task(pump_task)
                        await cancel_task(notify_task)
                        await cancel_active_turn()
                        mgr.end(session_id)
                        await websocket.send_json(
                            {"event": "ended", "turn_count": turn_count, "barge_in_count": barge_in_count}
                        )
                        closed_normally = True
                        break
                    elif cmd == "reset_text":
                        last_text_holder[0] = ""
                    else:
                        await websocket.send_json({"event": "warn", "msg": f"unknown cmd: {cmd}"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_session crashed")
    finally:
        closing = True
        await cancel_task(pump_task)
        await cancel_task(notify_task)
        await cancel_active_turn()
        try:
            await worker.stop()
        except Exception:
            pass
        if not closed_normally:
            # Browser went away without "end" — leave recorder open so the
            # dashboard can still read partial data.
            logger.info("[%s] ws closed without explicit end; turn_count=%d", session_id, turn_count)


def mount_websocket(app: FastAPI) -> None:
    """Register the /ws/session/{id} route."""
    @app.websocket("/ws/session/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await _ws_session_impl(websocket, session_id)