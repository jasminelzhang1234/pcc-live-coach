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
  /api/session/{id}/audio      GET   serve the recorded wav (dashboard inline player)
  /api/session/{id}/transcript GET   dialogue JSONL → [{role, turn, text, ms}]
  /api/session/{id}/rhythm     GET   per-turn rhythm features + KPIs
  /api/session/{id}/assess     POST  run pcc-assessor on the dialogue (LLM, slow)
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
import subprocess
import sys as _sys
import time
from datetime import datetime
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
AUTO_SUBMIT_DELAY_S = 0.4


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


@api_router.get("/session/{session_id}/transcript")
def session_transcript(session_id: str) -> dict:
    """Return the dialogue transcript for a session.

    Reads `sessions/dialogues/<id>.jsonl` (written continuously by
    router.write_dialogue during the WS pipeline). Filters to
    event=='utterance' rows and returns them chronologically. _meta rows
    (session_start / session_end / barge_in) are excluded — they aren't
    part of what the user reads as a transcript.

    Returns {session_id, turns: [{role, turn, text, ms}]} or 404 if the
    dialogue file hasn't been written yet.
    """
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    dialogue_path = Path(state.recorder.dialogue_path)
    if not dialogue_path.is_file():
        raise HTTPException(status_code=404, detail=f"transcript not yet available: {session_id}")
    turns = []
    with open(dialogue_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event") != "utterance":
                continue
            turns.append({
                "role": obj.get("role"),
                "turn": obj.get("turn"),
                "text": obj.get("text", ""),
                "ms": obj.get("ms"),
            })
    # Defensive sort: dialogue JSONL is written in arrival order, but if
    # barge_in inserts an out-of-band event, the JSONL ordering still holds
    # (barge_in is _meta, not an utterance, so it's filtered above).
    turns.sort(key=lambda t: (t.get("ms") or 0, t.get("turn") or 0))
    return {
        "session_id": session_id,
        "turns": turns,
    }


@api_router.get("/session/{session_id}/audio")
def session_audio(session_id: str):
    """Serve the recorded wav for inline `<audio>` playback in the dashboard.

    Returns the raw wav file produced by SessionRecorder.write_audio().
    404 if the session has no audio (in-flight session or probe-session
    that recorded nothing). The browser plays this directly via
    `<audio controls src="/api/session/{id}/audio">`.
    """
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    audio_path = Path(state.recorder.audio_path)
    if not audio_path.is_file() or state.recorder.audio_bytes() == 0:
        raise HTTPException(status_code=404, detail=f"audio not yet available: {session_id}")
    return FileResponse(
        str(audio_path),
        media_type="audio/wav",
        filename=f"{session_id}.wav",
    )


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
    """Aggregate per-turn features into dashboard KPI tiles.

    Marker 5.5 silence and CPM are coach-side metrics, so KPIs are
    computed over coach rows only. Client rows are still rendered in
    the table (so the user sees alternating coach/client) but excluded
    from KPI aggregation.
    """
    if not turns:
        return {"mean_cpm": 0, "silence_5_5_count": 0, "barge_in_count": 0, "turn_count": 0}
    coach_turns = [t for t in turns if t.get("speaker_role") == "coach"]
    if not coach_turns:
        return {"mean_cpm": 0, "silence_5_5_count": 0, "barge_in_count": 0, "turn_count": len(turns)}
    mean_cpm = sum(t.get("cpm", 0) for t in coach_turns) / len(coach_turns)
    silence_5_5_count = sum(1 for t in coach_turns if t.get("silence_5_5"))
    barge_in_count = sum(int(t.get("barge_in_count", 0)) for t in coach_turns)
    return {
        "mean_cpm": int(mean_cpm),
        "silence_5_5_count": silence_5_5_count,
        "barge_in_count": barge_in_count,
        "turn_count": len(coach_turns),
    }


def _chart_output_path(repo_root: Path) -> str:
    """Default trending-chart output path: progress/trending-chart-real-YYYY-MM-DD.html.

    Overridable via monkeypatch in tests to point at a tmp_path chart
    when the real script isn't being exercised.
    """
    return str(
        repo_root / "progress" / f"trending-chart-real-{datetime.now().strftime('%Y-%m-%d')}.html"
    )


@api_router.post("/session/{session_id}/track")
def session_track(session_id: str) -> dict:
    """Push the session to tracker CSV + regenerate the trending chart.

    Spec (Task 4, dashboard v2):
    1. Upsert one row into `progress/tracker-sessions.csv` (idempotent:
       existing session_id → drop old row, insert new).
    2. Re-run `scripts/gen_trending_chart_real.py` so the dashboard's
       "成长曲线" link reflects the latest tracker state.

    Returns:
        {session_id, csv_status, chart_path, kpis} where csv_status is
        one of "inserted" | "replaced" | "no_csv" (the last means the
        canonical CSV header is missing — caller decides how to react).

    Raises:
        404 if session / dialogue missing.
    """
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    dialogue_path = Path(state.recorder.dialogue_path)
    if not dialogue_path.is_file():
        raise HTTPException(status_code=404, detail=f"transcript not yet available: {session_id}")

    # Compute KPI from rhythm jsonl (same logic as /rhythm endpoint).
    rhythm_path = Path(state.recorder.rhythm_path)
    kpis: dict = {"mean_cpm": 0, "silence_5_5_count": 0, "barge_in_count": 0, "turn_count": 0}
    if rhythm_path.is_file():
        turns: List[dict] = []
        with open(rhythm_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        kpis = _compute_kpis(turns)

    # Upsert into the tracker CSV.
    from phase_b.config import get_settings
    from phase_b.tracker.csv_append import build_row, upsert_session_row

    settings = get_settings()
    csv_path = Path(settings.tracker_csv)
    if not csv_path.is_absolute():
        csv_path = Path(__file__).resolve().parents[2] / csv_path

    # _load_header isn't exposed; we read the header inline so we can
    # build a row matching it (build_row needs the header list).
    csv_status = "no_csv"
    if csv_path.is_file():
        import csv as _csv
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = _csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                header = []
        row = build_row(
            session_id=session_id,
            persona=state.persona_id,
            difficulty=state.difficulty,
            topic=state.topic,
            audio_path=state.recorder.audio_path,
            transcript_path=state.recorder.dialogue_path,
            header=header,
        )
        csv_status = upsert_session_row(csv_path=csv_path, row=row)

    # Trigger chart regeneration (subprocess; isolates script's sys.argv).
    chart_path: Optional[str] = None
    chart_error: Optional[str] = None
    try:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "gen_trending_chart_real.py"
        if script.is_file():
            proc = subprocess.run(
                [_sys.executable, str(script)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                chart_path = _chart_output_path(repo_root)
            else:
                chart_error = (proc.stderr or proc.stdout or "").strip()[:300]
                logger.warning("chart regen failed (rc=%s): %s", proc.returncode, chart_error)
        else:
            chart_error = f"chart script not found: {script}"
    except Exception as e:
        chart_error = str(e)
        logger.exception("chart regen crashed for %s", session_id)

    return {
        "session_id": session_id,
        "csv_status": csv_status,
        "chart_path": chart_path,
        "chart_error": chart_error,
        "kpis": kpis,
    }


@api_router.post("/session/{session_id}/assess")
async def session_assess(session_id: str) -> dict:
    """Run the PCC 37-marker assessment on a session's dialogue.

    Strategy (Task 3, A1 路线):把 4 个 KB 文件全文塞进 system prompt,让
    LLM 用同一份知识底座做判定。结果落盘 `assessments/<id>.json`,
    dashboard 直接读这份 json 渲染 ✔/△/✘。

    慢路径:30-90s(LLM reasoning_split + 25k token prompt)。前端通过
    spinner 等待;如果需要更短的反馈,可以加 force=1 跳过缓存。

    Returns:
        {session_id, summary, assessment_path} — assessment_path 用于
        dashboard 异步重读(若 LLM 之后追加了修正)。
    Raises:
        404 if session / dialogue missing
        502 if LLM parse fails
    """
    state = get_manager().get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    dialogue_path = Path(state.recorder.dialogue_path)
    if not dialogue_path.is_file():
        raise HTTPException(status_code=404, detail=f"transcript not yet available: {session_id}")

    # Read the dialogue JSONL into turns (same filter as /transcript endpoint).
    turns: List[dict] = []
    with open(dialogue_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event") != "utterance":
                continue
            turns.append({
                "role": obj.get("role"),
                "turn": obj.get("turn"),
                "text": obj.get("text", ""),
                "ms": obj.get("ms"),
            })

    # Run the assessment (LLM call).
    from phase_b.assess import run_assessment, save_assessment

    try:
        payload = await run_assessment(turns)
    except ValueError as e:
        # LLM returned malformed output — propagate as 502 so the dashboard
        # can show "评估失败,请重试" rather than swallowing the error.
        logger.exception("assess parse failed for %s", session_id)
        raise HTTPException(status_code=502, detail=f"assess parse failed: {e}") from e

    # Persist for the dashboard to read asynchronously + re-render later.
    out_path = save_assessment(session_id, payload)

    summary = payload.get("summary") or {}
    return {
        "session_id": session_id,
        "summary": summary,
        "assessment_path": str(out_path),
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
    worker = ASRWorker(sample_rate=16000)
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

    last_text_holder = [""]  # most recent ASR partial text (mirrored from pump_asr)
    turn_count = 0
    closed_normally = False
    closing = False
    barge_in_count = 0
    active_turn_task: Optional[asyncio.Task] = None  # running run_turn() — cancellable on barge-in
    last_auto_submit_key = [None]
    audio_diag_bytes = [0]  # rolling byte counter for the audio-level diagnostic log
    pending_auto_task: Optional[asyncio.Task] = None

    def is_plausible_auto_text(text: str) -> bool:
        compact = "".join((text or "").split())
        if len(compact) < 3:
            return False
        return not any(char in compact for char in "佢唔喺嚟系嗰咩")

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
        return tuple(event.get(field) for field in ("text", "audio_ms", "is_utterance_end"))

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
        auto_event_key = None
        if auto_event is not None:
            auto_event_key = utterance_identity(auto_event)
            if last_auto_submit_key[0] == auto_event_key:
                return False
            last_auto_submit_key[0] = auto_event_key

        turn_count += 1
        turn_started_ms = int(time.time() * 1000)
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
                if auto_event_key is not None and last_auto_submit_key[0] == auto_event_key:
                    last_auto_submit_key[0] = None
                if active_turn_task is asyncio.current_task():
                    active_turn_task = None

        active_turn_task = asyncio.create_task(run_one_turn(), name=f"turn-{session_id}-{turn_count}")
        return True

    async def cancel_pending_auto() -> None:
        nonlocal pending_auto_task
        task = pending_auto_task
        pending_auto_task = None
        await cancel_task(task)

    async def submit_stable_auto(event: dict) -> None:
        nonlocal pending_auto_task
        try:
            await asyncio.sleep(AUTO_SUBMIT_DELAY_S)
            if closing:
                return
            text = last_text_holder[0] or event.get("text", "")
            if is_plausible_auto_text(text):
                await submit_turn(text, auto_event=event)
        except asyncio.CancelledError:
            raise
        finally:
            if pending_auto_task is asyncio.current_task():
                pending_auto_task = None

    async def pump_asr() -> None:
        """Forward ASRWorker events to the browser as JSON, and mirror the
        latest partial text into ``last_text_holder`` so the speak handler can
        read it without racing the partial pump."""
        nonlocal pending_auto_task
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
                    and is_plausible_auto_text(ev.get("text", ""))
                ):
                    await cancel_pending_auto()
                    if AUTO_SUBMIT_DELAY_S == 0:
                        await submit_stable_auto(ev)
                    else:
                        pending_auto_task = asyncio.create_task(
                            submit_stable_auto(ev), name=f"auto-submit-{session_id}"
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
                        await cancel_task(load_task)
                        mgr.end(session_id)
                        await websocket.send_json(
                            {"event": "ended", "session_id": session_id, "turn_count": turn_count, "barge_in_count": barge_in_count}
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
        await cancel_task(load_task)
        try:
            await worker.stop()
        except Exception:
            pass
        if not closed_normally:
            try:
                mgr.end(session_id)
            except Exception:
                logger.exception("[%s] session cleanup failed", session_id)
            logger.info("[%s] ws closed without explicit end; turn_count=%d", session_id, turn_count)


def mount_websocket(app: FastAPI) -> None:
    """Register the /ws/session/{id} route."""
    @app.websocket("/ws/session/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await _ws_session_impl(websocket, session_id)