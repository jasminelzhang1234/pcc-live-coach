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
"""阿里云智能语音交互 — 实时语音识别客户端(基于 aliyun-nls SDK)。

替代 phase_b/asr/asr_worker.py 里的 FunASR(SenseVoiceSmall 离线 + 1.8s 静音触发),
改用阿里云 NLS 实时流式识别(WebSocket,partial 持续输出,句末 final)。

依赖(2026-09-06 已装):
    pip install aliyun-nls alibabacloud_nls_cloud_meta20190228

SDK 把 WebSocket 协议、鉴权、心跳、重连都封装好了 — 我们只负责:
1. 拿 token(SDK TokenClient.create_token,24h 缓存)
2. 启动 NlsSpeechTranscriber,把回调事件转成统一 schema
3. send_audio() 推 PCM(SDK 在内部线程跑)

事件 schema(与旧 ASRWorker 兼容):
    {"event": "partial", "text", "audio_ms", "latency_ms", "is_utterance_end": bool}
    {"event": "error",   "error": "..."}
    {"event": "done"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from queue import Queue
from typing import Optional

import nls
from alibabacloud_nls_cloud_meta20190228.client import Client as TokenClient
from alibabacloud_tea_openapi import models as open_api_models


logger = logging.getLogger(__name__)


# 模块级 token 缓存:{ak_id: (token, expire_epoch)}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


def _get_token_sync(ak_id: str, ak_secret: str) -> tuple[str, float]:
    """同步拿 token(SDK TokenClient 是同步的)。返回 (token, expire_epoch)。"""
    now = time.time()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(ak_id)
        if cached and cached[1] - 60 > now:
            return cached
        config = open_api_models.Config(
            access_key_id=ak_id,
            access_key_secret=ak_secret,
            region_id="cn-shanghai",
            endpoint="nls-meta.cn-shanghai.aliyuncs.com",
        )
        client = TokenClient(config)
        resp = client.create_token()
        token = resp.body.token.id
        expire = int(resp.body.token.expire_time)
        _TOKEN_CACHE[ak_id] = (token, expire)
        logger.info(
            "[aliyun-asr] token cached, expire=%s",
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expire)),
        )
        return token, expire


class AliyunASRClient:
    """阿里云实时语音识别客户端(WebSocket 流式)。

    用法:
        client = AliyunASRClient(appkey, ak_id, ak_secret)
        await client.start()                   # 阻塞 ~200ms(SDK 在内部线程跑 ws)
        client.feed(pcm_bytes)                 # 非阻塞(SDK send_audio 在内部线程)
        async for ev in client.events():       # 持续产出 partial/final/error
            ...
        await client.stop()                    # 发 stop,SDK 关 ws,触发 completed/close

    事件 schema:
        {"event": "partial", "text", "audio_ms", "latency_ms", "is_utterance_end": False}
        {"event": "partial", "text", ..., "is_utterance_end": True, "is_final": True}  # 句末
        {"event": "error",   "error": "..."}
        {"event": "done"}    # TranscriptionCompleted 后触发
    """

    WS_URL = "wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1"

    def __init__(
        self,
        appkey: str,
        ak_id: str,
        ak_secret: str,
        sample_rate: int = 16000,
        max_sentence_silence: int = 800,
        enable_intermediate_result: bool = True,
        enable_punctuation: bool = True,
    ) -> None:
        if not (appkey and ak_id and ak_secret):
            raise ValueError("appkey / ak_id / ak_secret 三项都不能为空")
        self._appkey = appkey
        self._ak_id = ak_id
        self._ak_secret = ak_secret
        self._sample_rate = sample_rate
        self._max_sentence_silence = max_sentence_silence
        self._enable_intermediate = enable_intermediate_result
        self._enable_punc = enable_punctuation
        self._transcriber: Optional[nls.NlsSpeechTranscriber] = None
        self._events_q: Queue[dict] = Queue()
        self._t_start = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._done = False

    # --- SDK 回调(SDK 线程里被调用)-----------------------------

    def _on_start(self, msg: str, *args) -> None:
        logger.info("[aliyun-asr] transcription started: %s", msg[:120])

    def _on_result_changed(self, msg: str, *args) -> None:
        # partial:中间识别结果
        try:
            data = json.loads(msg)
            payload = data.get("payload", {}) or {}
            text = (payload.get("result") or "").strip()
            audio_ms = int(payload.get("time", 0) or 0)
        except (json.JSONDecodeError, AttributeError, ValueError, TypeError) as e:
            logger.warning("[aliyun-asr] _on_result_changed parse fail: %s msg=%s", e, (msg or "")[:200])
            return
        if not text:
            return
        self._events_q.put({
            "event": "partial",
            "text": text,
            "audio_ms": audio_ms,
            "latency_ms": int((time.time() - self._t_start) * 1000),
            "is_utterance_end": False,
        })

    def _on_sentence_end(self, msg: str, *args) -> None:
        # 句末:完整识别
        try:
            data = json.loads(msg)
            payload = data.get("payload", {}) or {}
            text = (payload.get("result") or "").strip()
            audio_ms = int(payload.get("time", 0) or 0)
        except (json.JSONDecodeError, AttributeError, ValueError, TypeError):
            text = ""
            audio_ms = 0
        self._events_q.put({
            "event": "partial",
            "text": text,
            "audio_ms": audio_ms,
            "latency_ms": int((time.time() - self._t_start) * 1000),
            "is_utterance_end": True,
            "is_final": True,
        })

    def _on_completed(self, msg: str, *args) -> None:
        logger.info("[aliyun-asr] transcription completed: %s", msg[:80])
        self._events_q.put({"event": "done"})
        self._done = True

    def _on_error(self, msg: str, *args) -> None:
        logger.error("[aliyun-asr] error: %s", msg[:200])
        self._events_q.put({"event": "error", "error": msg[:500]})

    def _on_close(self, *args) -> None:
        logger.info("[aliyun-asr] connection closed")
        # close 后确保 pump 退出
        if not self._done:
            self._events_q.put({"event": "done"})
            self._done = True

    # --- 公开 API----------------------------------------------

    async def start(self) -> None:
        """同步换 token(在线程池跑 SDK)+ 同步启动 SDK 的 WebSocket 客户端。"""
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._t_start = time.time()
        # 1. 拿 token(SDK TokenClient 是阻塞的,扔线程池)
        token, _ = await loop.run_in_executor(None, _get_token_sync, self._ak_id, self._ak_secret)
        # 2. 构造 transcriber
        self._transcriber = nls.NlsSpeechTranscriber(
            url=self.WS_URL,
            appkey=self._appkey,
            token=token,
            on_start=self._on_start,
            on_result_changed=self._on_result_changed,
            on_sentence_end=self._on_sentence_end,
            on_completed=self._on_completed,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # 3. 启动 WebSocket(SDK start() 是非阻塞,SDK 在内部线程跑 ws)
        await loop.run_in_executor(None, lambda: self._transcriber.start(
            aformat="pcm",
            sample_rate=self._sample_rate,
            ch=1,
            enable_intermediate_result=self._enable_intermediate,
            enable_punctuation_prediction=self._enable_punc,
            ex={"max_sentence_silence": self._max_sentence_silence},
        ))
        logger.info("[aliyun-asr] client started, ws_url=%s", self.WS_URL)

    def feed(self, pcm_bytes: bytes) -> None:
        """非阻塞推送 PCM(SDK send_audio 在内部线程里发送)。"""
        if self._transcriber is None or not pcm_bytes:
            return
        try:
            self._transcriber.send_audio(pcm_bytes)
        except Exception:
            logger.exception("send_audio failed (chunk dropped)")

    async def events(self) -> "asyncio.AsyncIterator[dict]":
        """异步迭代产出 partial / error / done。"""
        loop = asyncio.get_running_loop()
        while True:
            # 从同步 queue 异步读
            ev = await loop.run_in_executor(None, self._events_q.get)
            yield ev
            if ev.get("event") == "done":
                return

    async def stop(self) -> None:
        """发 stop 帧,SDK 关 ws,触发 on_completed/on_close → events() 收 done 后退出。"""
        if self._transcriber is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._transcriber.stop)
        except Exception:
            logger.exception("transcriber.stop failed")
        # 给 done 一点时间传播
        await asyncio.sleep(0.2)