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
    let nextToken = 0;
    let pendingToken = null;
    let activeToken = null;
    return {
      trySubmit() {
        if (pendingToken !== null || activeToken !== null) return null;
        pendingToken = ++nextToken;
        return pendingToken;
      },
      markActive(token) {
        if (pendingToken !== token) return false;
        pendingToken = null;
        activeToken = token;
        return true;
      },
      releasePending(token) {
        if (pendingToken !== token) return false;
        pendingToken = null;
        return true;
      },
      release(token) {
        if (token == null || token === pendingToken || token === activeToken) {
          pendingToken = null;
          activeToken = null;
          return true;
        }
        return false;
      },
      currentToken() {
        return activeToken !== null ? activeToken : pendingToken;
      },
    };
  }

  function resetReplyState({ activeSources }) {
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
      replyAborted: false,
    };
  }

  return {
    createTurnLock,
    resetReplyAfterClose: resetReplyState,
    resetReplyAfterError: resetReplyState,
    routeAudioFrame,
  };
});