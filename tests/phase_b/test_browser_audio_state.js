const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createTurnLock,
  resetReplyAfterError,
  resetReplyAfterClose,
  routeAudioFrame,
} = require("../../phase_b/static/audio_state.js");

test("playing audio detects barge-in without uploading the frame to ASR", () => {
  const result = routeAudioFrame({
    playing: true,
    rms: 0.05,
    loudFrames: 2,
    threshold: 0.02,
    debounceFrames: 3,
  });

  assert.equal(result.sendBargeIn, true);
  assert.equal(result.uploadToAsr, false);
});

test("listening audio uploads PCM and never sends barge-in", () => {
  const result = routeAudioFrame({
    playing: false,
    rms: 0.05,
    loudFrames: 0,
    threshold: 0.02,
    debounceFrames: 3,
  });

  assert.equal(result.sendBargeIn, false);
  assert.equal(result.uploadToAsr, true);
});

test("playing audio resets the loud-frame debounce on a quiet frame", () => {
  const result = routeAudioFrame({
    playing: true,
    rms: 0.01,
    loudFrames: 2,
    threshold: 0.02,
    debounceFrames: 3,
  });

  assert.equal(result.loudFrames, 0);
  assert.equal(result.sendBargeIn, false);
  assert.equal(result.uploadToAsr, false);
});

test("playing audio emits barge-in only when the debounce threshold is crossed", () => {
  const result = routeAudioFrame({
    playing: true,
    rms: 0.05,
    loudFrames: 3,
    threshold: 0.02,
    debounceFrames: 3,
  });

  assert.equal(result.loudFrames, 4);
  assert.equal(result.sendBargeIn, false);
  assert.equal(result.uploadToAsr, false);
});

test("continuous loud frames send barge-in only on the threshold frame", () => {
  let loudFrames = 0;
  const sends = [];

  for (let i = 0; i < 5; i++) {
    const result = routeAudioFrame({
      playing: true,
      rms: 0.05,
      loudFrames,
      threshold: 0.02,
      debounceFrames: 3,
    });
    loudFrames = result.loudFrames;
    sends.push(result.sendBargeIn);
  }

  assert.deepEqual(sends, [false, false, true, false, false]);
});

test("turn lock blocks duplicate manual submits until a terminal event", () => {
  const lock = createTurnLock();

  const token = lock.trySubmit();
  assert.ok(token);
  assert.equal(lock.trySubmit(), null);
  lock.release(token);
  assert.ok(lock.trySubmit());
  lock.release();
  assert.ok(lock.trySubmit());
});

test("warn releases only the matching pending submit, not an active turn", () => {
  const lock = createTurnLock();
  const pendingToken = lock.trySubmit();

  assert.equal(lock.releasePending(pendingToken), true);
  assert.equal(lock.trySubmit() !== null, true);

  const activeToken = lock.currentToken();
  lock.markActive(activeToken);
  assert.equal(lock.releasePending(activeToken), false);
  assert.equal(lock.trySubmit(), null);
  lock.release(activeToken);
  assert.ok(lock.trySubmit());
});

test("stale warn cannot release a newer pending submit", () => {
  const lock = createTurnLock();
  const staleToken = lock.trySubmit();
  lock.release(staleToken);
  const currentToken = lock.trySubmit();

  assert.equal(lock.releasePending(staleToken), false);
  assert.equal(lock.currentToken(), currentToken);
});

test("error reset stops queued sources and clears reply playback state", () => {
  const stopped = [];
  const result = resetReplyAfterError({
    activeSources: [
      { stop: () => stopped.push("first") },
      { stop: () => stopped.push("second") },
    ],
  });

  assert.deepEqual(stopped, ["first", "second"]);
  assert.deepEqual(result, {
    activeSources: [],
    nextPlayTime: 0,
    loudFrames: 0,
    bargeInSent: false,
    replyPlaying: false,
    replyStreamEnded: true,
    replyAborted: false,
  });
});

test("error reset drops old PCM but allows the next reply to play", () => {
  const errorReset = resetReplyAfterError({
    activeSources: [{ stop() {} }],
  });

  assert.equal(errorReset.replyAborted, false);
  assert.equal(errorReset.replyPlaying, false);

  const nextReply = {
    ...errorReset,
    replyPlaying: true,
    replyStreamEnded: false,
  };
  assert.equal(nextReply.replyAborted, false);
  assert.equal(nextReply.replyPlaying, true);
});

test("close reset stops queued sources and clears reply playback state", () => {
  const stopped = [];
  const result = resetReplyAfterClose({
    activeSources: [{ stop: () => stopped.push("source") }],
  });

  assert.deepEqual(stopped, ["source"]);
  assert.deepEqual(result, {
    activeSources: [],
    nextPlayTime: 0,
    loudFrames: 0,
    bargeInSent: false,
    replyPlaying: false,
    replyStreamEnded: true,
    replyAborted: false,
  });
});