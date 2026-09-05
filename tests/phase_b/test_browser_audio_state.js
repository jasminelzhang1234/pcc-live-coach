const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createTurnLock,
  resetReplyAfterError,
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

  assert.equal(lock.trySubmit(), true);
  assert.equal(lock.trySubmit(), false);
  lock.release();
  assert.equal(lock.trySubmit(), true);
  lock.release();
  assert.equal(lock.trySubmit(), true);
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
  });
});