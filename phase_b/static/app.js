/* PCC Live Coach — Step 7 client.
   Pipeline: getUserMedia (16kHz mono) → WS binary PCM →
   server-side ASRWorker (partials) → click "说" →
   run_turn() → LLM text + TTS PCM → WebAudio playback.
   Step 7 adds barge-in: if mic detects speech during TTS playback,
   stop playback and send {"cmd":"barge_in"} so the server cancels the turn.
*/

(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  let routeAudioFrame = null;
  let createTurnLock = null;
  let resetReplyAfterError = null;
  let resetReplyAfterClose = null;

  async function loadAudioState() {
    if (routeAudioFrame) return;
    if (!window.PccAudioState) await import("/static/audio_state.js");
    routeAudioFrame = window.PccAudioState && window.PccAudioState.routeAudioFrame;
    createTurnLock = window.PccAudioState && window.PccAudioState.createTurnLock;
    resetReplyAfterError = window.PccAudioState && window.PccAudioState.resetReplyAfterError;
    resetReplyAfterClose = window.PccAudioState && window.PccAudioState.resetReplyAfterClose;
    if (!routeAudioFrame || !createTurnLock || !resetReplyAfterError || !resetReplyAfterClose) {
      throw new Error("audio state helper unavailable");
    }
  }

  // ---- View switching ----------------------------------------------------
  function show(pageId) {
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    const target = document.getElementById(pageId);
    if (target) target.classList.add("active");
  }
  window.__showPage = show;

  // ---- Persona list -------------------------------------------------------
  async function populatePersonaSelect() {
    const sel = $("#persona-select");
    sel.innerHTML = "";
    try {
      const res = await fetch("/api/personas");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const ids = await res.json();
      if (!Array.isArray(ids) || ids.length === 0) {
        sel.innerHTML = '<option value="">(无可用人格)</option>';
        return;
      }
      for (const persona of ids) {
        const opt = document.createElement("option");
        opt.value = persona.id;
        const line = persona.line ? ` · ${persona.line}` : "";
        const diff = persona.difficulty ? ` (难度 ${persona.difficulty})` : "";
        opt.textContent = `${persona.name || persona.id}${line}${diff}`;
        if (persona.id === "vec-01") opt.selected = true;
        sel.appendChild(opt);
      }
    } catch (e) {
      console.error("persona fetch failed", e);
      sel.innerHTML = '<option value="">(加载失败)</option>';
    }
  }

  // ---- Transcript helpers -------------------------------------------------
  function appendLine(role, text, cls) {
    const div = document.createElement("div");
    div.className = "line " + (cls || (role === "coach" ? "coach" : "client"));
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = role === "coach" ? "教练" : role === "client" ? "客户" : role;
    const body = document.createElement("span");
    body.className = "body";
    body.textContent = text;
    div.appendChild(tag);
    div.appendChild(body);
    const wrap = $("#transcript");
    wrap.appendChild(div);
    wrap.scrollTop = wrap.scrollHeight;
    return div;
  }

  function setStatus(msg) {
    $("#session-status").textContent = msg;
  }

  function setLatency(ms) {
    $("#latency-readout").textContent = ms == null ? "— ms" : `${ms} ms`;
  }

  // ---- Session globals ---------------------------------------------------
  let ws = null;
  let audioCtx = null;
  let mediaSource = null;
  let processor = null;
  let micStream = null;
  let micOn = false;
  let activeSession = null;
  let lastPartialDiv = null;
  let replyPlaying = false;
  let nextPlayTime = 0; // AudioContext currentTime cursor for queued PCM
  let activeSources = []; // BufferSourceNodes scheduled for playback — barge-in stops them
  let bargeInSent = false; // guard: only send one barge_in per reply
  let replyStreamEnded = false;
  let replyAborted = false;
  let turnLock = null;
  let turnToken = null;

  // ---- Barge-in tuning ---------------------------------------------------
  // RMS threshold over a single 256ms frame (float32 samples, range ~[-1,1]).
  // 0.02 ≈ roughly normal conversational volume against a quiet room.
  const BARGE_IN_RMS_THRESHOLD = 0.02;
  // Number of consecutive "loud" frames required to trigger barge-in.
  // 256ms * 3 = 768ms — slightly longer than the 500ms target in the plan
  // because AEC echo is most prominent in the first 500ms after a chunk starts.
  const BARGE_IN_DEBOUNCE_FRAMES = 3;
  let bargeInLoudFrames = 0;

  function resetBargeInDebounce() {
    bargeInLoudFrames = 0;
    bargeInSent = false;
  }

  function finishReplyPlaybackIfDrained() {
    if (!replyStreamEnded || activeSources.length > 0) return;
    replyPlaying = false;
    setStatus("回复结束 — 继续说话");
  }

  function stopAllAudio() {
    for (const s of activeSources) {
      try { s.stop(); } catch {}
    }
    activeSources = [];
    nextPlayTime = 0;
  }

  // ---- Start session ------------------------------------------------------
  $("#btn-start").addEventListener("click", async () => {
    const persona = $("#persona-select").value;
    const difficulty = parseInt($("#difficulty-select").value, 10) || 2;
    const topicInput = $("#topic-input");
    const topic = topicInput ? topicInput.value.trim() : "";
    if (!persona) {
      alert("请先选择人格");
      return;
    }
    $("#btn-start").disabled = true;
    setStatus("正在开启会话…");
    try {
      const res = await fetch("/api/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona_id: persona, topic, difficulty }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      activeSession = await res.json();
      $("#session-title").textContent = `对话中 · ${activeSession.persona_id}`;
      show("page-session");
      await connectWs(activeSession.id);
    } catch (e) {
      console.error("start failed", e);
      alert("开启失败:" + e.message);
      $("#btn-start").disabled = false;
    }
  });

  // ---- WebSocket connect --------------------------------------------------
  async function connectWs(sessionId) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/session/${sessionId}`;
    ws = new WebSocket(url);
    const socket = ws;
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      setStatus("已连接 — 等待 ASR 就绪…");
    };

    ws.onmessage = async (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        enqueuePcm(new Uint8Array(ev.data));
        return;
      }
      let obj;
      try { obj = JSON.parse(ev.data); } catch { return; }
      switch (obj.event) {
        case "ready":
          setStatus(`已连接 · persona=${obj.persona_id} — 点击麦克风开始`);
          break;
        case "asr_ready":
          setStatus("ASR 就绪 — 点击麦克风开始");
          break;
        case "partial": {
          // Ignore stale ASR partials during TTS playback. The server's
          // ASRWorker still has audio buffered from BEFORE the reply
          // started (mic bleed, environment noise, end of the previous
          // utterance). When mic capture is muted during playback those
          // buffered frames trigger silence-based decode and emit
          // phantom partials like "嗯" / "你想在" — those aren't real
          // coach speech and shouldn't show up as a new coach line.
          if (replyPlaying) break;
          let t = obj.text || "";
          // SenseVoiceSmall hallucinates 1-2 char noise as actual speech
          // ("你", "自", "y", "hello") when the buffer is mostly silence
          // or TTS bleed. Drop those — they're not useful to display or
          // commit, and committing one of them produced nonsensical LLM
          // replies in the 2026-09-05 session.
          if (t.replace(/[\s　]/g, "").length < 2) break;
          // Don't shrink a previously-shown partial: if a new partial is
          // shorter than the current line (model backtracked), keep the
          // longer one so the user sees what they said, not what the model
          // briefly guessed.
          if (lastPartialDiv) {
            const prev = lastPartialDiv.querySelector(".body").textContent || "";
            if (prev.length > t.length) t = prev;
          }
          if (!lastPartialDiv) {
            lastPartialDiv = appendLine("教练(实时)", t || "…", "partial");
          } else {
            lastPartialDiv.querySelector(".body").textContent = t || "…";
          }
          setLatency(obj.latency_ms);
          break;
        }
        case "reply_text": {
          if (replyAborted) break;
          if (turnLock && turnToken !== null) turnLock.markActive(turnToken);
          if (lastPartialDiv) {
            lastPartialDiv.classList.remove("partial");
            lastPartialDiv = null;
          }
          appendLine("客户", obj.text || "");
          setStatus("正在播放回复…说话可打断");
          replyPlaying = true;
          replyStreamEnded = false;
          nextPlayTime = audioCtx ? audioCtx.currentTime + 0.05 : 0;
          resetBargeInDebounce();
          break;
        }
        case "reply_end":
          // reply_end means the server finished SENDING PCM, not that
          // playback finished. The queued BufferSourceNodes will play out
          // naturally; calling stopAllAudio() here was cutting the tail of
          // the reply (visible when text was short — the next ~2s of audio
          // got killed before the last chunks had a chance to play).
          // Cleanup happens automatically via the onended handler in
          // enqueuePcm which splices each node out of activeSources when it
          // finishes playing.
          replyStreamEnded = true;
          if (turnLock) turnLock.release(turnToken);
          turnToken = null;
          finishReplyPlaybackIfDrained();
          break;
        case "barge_in_stopped":
          replyPlaying = false;
          replyStreamEnded = true;
          stopAllAudio();
          resetBargeInDebounce();
          if (lastPartialDiv) {
            lastPartialDiv.classList.remove("partial");
            lastPartialDiv = null;
          }
          if (turnLock) turnLock.release(turnToken);
          turnToken = null;
          setStatus("已打断 — 继续说话");
          break;
        case "warn":
          console.warn("server warn:", obj.msg);
          if (turnLock && turnToken !== null && turnLock.releasePending(turnToken)) {
            turnToken = null;
          }
          break;
        case "error":
          console.error("server error:", obj);
          if (!resetReplyAfterError) break;
          const reset = resetReplyAfterError({ activeSources });
          activeSources = reset.activeSources;
          nextPlayTime = reset.nextPlayTime;
          bargeInLoudFrames = reset.loudFrames;
          bargeInSent = reset.bargeInSent;
          replyPlaying = reset.replyPlaying;
          replyStreamEnded = reset.replyStreamEnded;
          replyAborted = reset.replyAborted;
          if (turnLock) turnLock.release(turnToken);
          turnToken = null;
          setStatus(`错误(${obj.stage || "?"}):${obj.error}`);
          break;
        case "ended":
          // Capture session_id BEFORE teardownSession() nulls activeSession.
          const endedSid = obj.session_id || (activeSession && activeSession.id);
          await teardownSession();
          show("page-dashboard");
          $("#dashboard-session-id").textContent =
            `${endedSid || "?"} · ${obj.turn_count || 0} turns · ${obj.barge_in_count || 0} barge-in`;
          if (endedSid) await loadRhythm(endedSid);
          break;
        default:
          // ignore unknown
      }
    };

    ws.onclose = () => {
      if (ws !== socket) return;
      stopMic();
      if (resetReplyAfterClose) {
        const reset = resetReplyAfterClose({ activeSources });
        activeSources = reset.activeSources;
        nextPlayTime = reset.nextPlayTime;
        bargeInLoudFrames = reset.loudFrames;
        bargeInSent = reset.bargeInSent;
        replyPlaying = reset.replyPlaying;
        replyStreamEnded = reset.replyStreamEnded;
      } else {
        stopAllAudio();
        replyPlaying = false;
        replyStreamEnded = true;
      }
      if (lastPartialDiv) {
        lastPartialDiv.remove();
        lastPartialDiv = null;
      }
      if (turnLock) turnLock.release(turnToken);
      turnToken = null;
      resetBargeInDebounce();
      replyAborted = false;
      ws = null;
      setStatus("连接已关闭");
    };
    ws.onerror = (e) => {
      console.error("ws error", e);
      setStatus("WS 出错");
    };
  }

  // ---- Mic toggle --------------------------------------------------------
  $("#btn-mic").addEventListener("click", async () => {
    if (micOn) stopMic();
    else await startMic();
  });

  async function startMic() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setStatus("WS 未就绪");
      return;
    }
    try {
      await loadAudioState();
    } catch (e) {
      console.error("audio state helper failed", e);
      setStatus("音频状态初始化失败");
      return;
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      console.error("getUserMedia failed", e);
      setStatus("麦克风权限被拒");
      return;
    }

    audioCtx = new AudioContext({ sampleRate: 16000 });
    mediaSource = audioCtx.createMediaStreamSource(micStream);
    processor = audioCtx.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      if (!micOn || !ws || ws.readyState !== WebSocket.OPEN) return;
      const f32 = e.inputBuffer.getChannelData(0);
      let rms = 0;
      if (replyPlaying) {
        let sumSq = 0;
        for (let i = 0; i < f32.length; i++) sumSq += f32[i] * f32[i];
        rms = Math.sqrt(sumSq / f32.length);
      }
      const route = routeAudioFrame({
        playing: replyPlaying,
        rms,
        loudFrames: bargeInLoudFrames,
        threshold: BARGE_IN_RMS_THRESHOLD,
        debounceFrames: BARGE_IN_DEBOUNCE_FRAMES,
      });
      bargeInLoudFrames = route.loudFrames;
      if (route.sendBargeIn && !bargeInSent) {
        bargeInSent = true;
        try {
          ws.send(JSON.stringify({ cmd: "barge_in" }));
          console.info("barge_in sent (rms=", rms.toFixed(3), ")");
        } catch (err) {
          console.warn("barge_in send failed", err);
        }
      }
      if (!route.uploadToAsr) return;
      const i16 = new Int16Array(f32.length);
      for (let i = 0; i < f32.length; i++) {
        const s = Math.max(-1, Math.min(1, f32[i]));
        i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      try {
        ws.send(i16.buffer);
      } catch (err) {
        console.warn("ws send failed", err);
      }
    };

    const sink = audioCtx.createGain();
    sink.gain.value = 0;
    mediaSource.connect(processor);
    processor.connect(sink);
    sink.connect(audioCtx.destination);

    micOn = true;
    $("#btn-mic").classList.add("active");
    setStatus("🎙 录音中 — 自动识别并提交");
  }

  function stopMic() {
    micOn = false;
    $("#btn-mic").classList.remove("active");
    if (processor) {
      try { processor.disconnect(); } catch {}
      processor.onaudioprocess = null;
      processor = null;
    }
    if (mediaSource) {
      try { mediaSource.disconnect(); } catch {}
      mediaSource = null;
    }
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      micStream = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    setStatus("麦克风已关闭");
  }

  // ---- TTS playback queue -------------------------------------------------
  function enqueuePcm(u8) {
    if (!audioCtx || !replyPlaying || replyAborted) return;
    const i16 = new Int16Array(u8.buffer, u8.byteOffset, u8.byteLength / 2);
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
    const buf = audioCtx.createBuffer(1, f32.length, 16000);
    buf.copyToChannel(f32, 0);
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    const now = audioCtx.currentTime;
    if (!nextPlayTime || nextPlayTime < now) nextPlayTime = now + 0.05;
    src.start(nextPlayTime);
    activeSources.push(src);
    src.onended = () => {
      const idx = activeSources.indexOf(src);
      if (idx >= 0) activeSources.splice(idx, 1);
      finishReplyPlaybackIfDrained();
    };
    nextPlayTime += buf.duration;
  }

  // ---- Speak commit ------------------------------------------------------
  $("#btn-speak").addEventListener("click", async () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (replyPlaying) return; // ignore during playback
    if (!turnLock) {
      try { await loadAudioState(); } catch { return; }
      turnLock = createTurnLock();
    }
    const token = turnLock.trySubmit();
    if (token === null) return;
    turnToken = token;
    replyAborted = false;
    if (lastPartialDiv) {
      lastPartialDiv.classList.remove("partial");
      lastPartialDiv = null;
    }
    ws.send(JSON.stringify({ cmd: "speak" }));
    setStatus("已提交 — 等待 LLM + TTS…");
  });

  // ---- End session -------------------------------------------------------
  $("#btn-end").addEventListener("click", async () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ cmd: "end" }));
    } else {
      const sid = activeSession && activeSession.id;
      await teardownSession();
      show("page-dashboard");
      if (sid) await loadRhythm(sid);
    }
  });

  async function teardownSession() {
    stopMic();
    stopAllAudio();
    if (ws) {
      const socket = ws;
      ws = null;
      try { socket.close(); } catch {}
    }
    activeSession = null;
    nextPlayTime = 0;
    activeSources = [];
    replyPlaying = false;
    replyStreamEnded = false;
    replyAborted = false;
    if (turnLock) turnLock.release(turnToken);
    turnToken = null;
    resetBargeInDebounce();
    $("#btn-mic").classList.remove("active");
    $("#btn-start").disabled = false;
  }

  $("#btn-back").addEventListener("click", () => show("page-entry"));

  // ---- Dashboard rhythm loader -------------------------------------------
  async function loadRhythm(sessionId) {
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/rhythm`);
      if (!res.ok) {
        console.warn("rhythm fetch failed", res.status);
        $("#kpi-cpm").textContent = "—";
        $("#kpi-silence").textContent = "—";
        $("#kpi-barge").textContent = "—";
        return;
      }
      const data = await res.json();
      const k = data.kpis || {};
      $("#kpi-cpm").textContent = k.mean_cpm != null ? String(k.mean_cpm) : "—";
      $("#kpi-silence").textContent = k.silence_5_5_count != null ? String(k.silence_5_5_count) : "—";
      $("#kpi-barge").textContent = k.barge_in_count != null ? String(k.barge_in_count) : "—";
      const tbody = document.querySelector("#turn-table tbody");
      if (tbody) {
        tbody.innerHTML = "";
        for (const t of data.turns || []) {
          const tr = document.createElement("tr");
          tr.innerHTML =
            `<td>${t.turn}</td>` +
            `<td>${t.speaker_role || ""}</td>` +
            `<td>${t.cpm != null ? t.cpm : ""}</td>` +
            `<td>${t.pre_silence_ms != null ? t.pre_silence_ms : ""}</td>` +
            `<td>${t.silence_5_5 ? "✔" : "·"}</td>` +
            `<td>${t.barge_in_count || 0}</td>`;
          tbody.appendChild(tr);
        }
      }
    } catch (e) {
      console.error("loadRhythm failed", e);
    }
  }

  populatePersonaSelect();
})();