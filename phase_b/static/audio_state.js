(function (root, factory) {
  const audioState = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = audioState;
  }
  root.PccAudioState = audioState;
})(typeof globalThis === "object" ? globalThis : this, function () {
  function routeAudioFrame({ playing, rms, loudFrames, threshold, debounceFrames }) {
    if (!playing) {
      return { loudFrames: 0, sendBargeIn: false, uploadToAsr: true };
    }

    const nextLoudFrames = rms > threshold ? loudFrames + 1 : 0;
    return {
      loudFrames: nextLoudFrames,
      sendBargeIn: nextLoudFrames === debounceFrames,
      uploadToAsr: false,
    };
  }

  function createTurnLock() {
    let locked = false;
    return {
      trySubmit() {
        if (locked) return false;
        locked = true;
        return true;
      },
      release() {
        locked = false;
      },
    };
  }

  function resetReplyAfterError({ activeSources }) {
    for (const source of activeSources) {
      try { source.stop(); } catch {}
    }
    return {
      activeSources: [],
      nextPlayTime: 0,
      loudFrames: 0,
      bargeInSent: false,
      replyPlaying: false,
      replyStreamEnded: true,
    };
  }

  return { createTurnLock, resetReplyAfterError, routeAudioFrame };
});