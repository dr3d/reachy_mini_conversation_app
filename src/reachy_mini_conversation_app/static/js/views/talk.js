/**
 * Talk view: conversation orb driven by the RPC activity stream.
 * Audio I/O runs entirely in Python; the orb doubles as the mic toggle.
 * Robot stays live, tapping the orb only mutes or unmutes the user's mic.
 */

import { applyPersonality, getMicState, listPersonalities, setMicMuted, subscribe } from "../api.js";
import { ORB_STATES } from "../constants.js";
import { createOrb, mapActivityToState } from "../orb.js";
import { consumePendingApply } from "../pending-apply.js";
import { setPersonality } from "../personality-badge.js";
import { h, prettifyProfileName } from "../ui.js";

const CAPTION_BY_STATE = Object.freeze({
  [ORB_STATES.MUTED]: "Muted",
  [ORB_STATES.IDLE]: "Ready",
  [ORB_STATES.CONNECTING]: "Connecting to the backend...",
  [ORB_STATES.LISTENING]: "Listening",
  [ORB_STATES.THINKING]: "Thinking",
  [ORB_STATES.SPEAKING]: "Speaking",
  [ORB_STATES.ERROR]: "Connection error",
});

const MAX_LOG_ITEMS = 80;
const ACTIVITY_LOG_LABELS = Object.freeze({
  response_created: "Thinking",
  tool_call_received: "Tool call",
  tool_result_ready: "Tool result",
  assistant_transcript_done: "Spoken",
});

export async function mountTalkView({ outlet, signal }) {
  const pending = consumePendingApply();
  const micStatePromise = getMicState().catch((error) => {
    console.warn("Failed to load microphone state", error);
    return null;
  });
  let muted = false;
  let micReady = false;
  let togglePending = false;
  let activePersonality = null;
  let subscription = null;
  let lastUserTranscript = "";
  let lastAssistantTranscript = "";

  const caption = h(
    "p",
    { class: "talk__caption", role: "status", "aria-live": "polite" },
    CAPTION_BY_STATE[ORB_STATES.CONNECTING]
  );
  const cameraImage = h("img", {
    class: "talk-camera__image",
    alt: "Current image",
    loading: "eager",
  });
  const cameraStatus = h("span", { class: "talk-camera__status" }, "");
  const cameraTitle = h("h2", { class: "talk-camera__title" }, "Current Image");
  const cameraPane = h(
    "section",
    { class: "talk-camera", "aria-label": "Current image", hidden: "hidden" },
    h("div", { class: "talk-camera__header" }, cameraTitle, cameraStatus),
    cameraImage
  );
  const logStatus = h("span", { class: "talk-log__status" }, "Live");
  const logItems = h("ol", { class: "talk-log__items", "aria-live": "polite" });
  const logPane = h(
    "section",
    { class: "talk-log", "aria-label": "Round log" },
    h("div", { class: "talk-log__header" }, h("h2", { class: "talk-log__title" }, "Round Log"), logStatus),
    logItems
  );
  const defaultAction = document.querySelector('[data-component="default-personality-action"]');
  if (defaultAction) {
    defaultAction.hidden = true;
    defaultAction.addEventListener("click", onSetDefault);
  }
  const orb = createOrb({
    initialState: ORB_STATES.CONNECTING,
    onStateChange: (state) => {
      caption.textContent = CAPTION_BY_STATE[state] || "";
    },
  });
  orb.root.disabled = true;
  orb.root.addEventListener("click", onMicTap);
  syncMicAria();

  signal.addEventListener("abort", cleanup, { once: true });

  const view = h(
    "section",
    { class: "view view--talk" },
    h("div", { class: "talk__orb-wrap" }, orb.root),
    caption,
    cameraPane,
    logPane
  );
  outlet.replaceChildren(view);

  if (pending) {
    caption.textContent = `Applying "${prettifyProfileName(pending.name)}"…`;
    try {
      await pending.promise;
    } catch (error) {
      if (signal.aborted) return;
      orb.setState(ORB_STATES.ERROR);
      caption.textContent = `Failed to apply personality: ${error?.message || error}`;
      return;
    }
    if (signal.aborted) return;
    // The activity subscription will flip the orb to its resting state next tick.
    caption.textContent = CAPTION_BY_STATE[ORB_STATES.CONNECTING];
    void refreshPersonalityState();
  } else {
    // Deep link to /talk with no pending apply: refresh the header badge.
    void refreshPersonalityState();
  }

  const micState = await micStatePromise;
  if (micState) muted = Boolean(micState.muted);
  if (signal.aborted) return;
  micReady = true;
  orb.root.disabled = false;
  syncMicAria();

  subscription = subscribeConversationEvents({
    // Re-sync mic state after subscribing: another tab may have toggled it.
    onReady: async () => {
      if (!togglePending) {
        try {
          muted = Boolean((await getMicState())?.muted);
        } catch {
          // keep the last known mute state
        }
      }
      if (signal.aborted) return;
      orb.setState(restingState());
      caption.textContent = CAPTION_BY_STATE[restingState()];
      syncMicAria();
    },
    onActivity: (reason) => {
      if (muted) return;
      const next = mapActivityToState(reason);
      if (next == null) return;
      orb.setState(next);
      const label = ACTIVITY_LOG_LABELS[reason];
      if (label) appendLogEntry("activity", label, prettifyActivity(reason));
    },
    onTranscript: ({ role, text, final }) => {
      if (!final || !text) return;
      if (role === "user") lastUserTranscript = compactText(text);
      if (role === "assistant") lastAssistantTranscript = compactText(text);
      appendLogEntry(role === "user" ? "user" : "assistant", role === "user" ? "User" : "Reachy", text);
    },
    onLog: ({ role, content }) => {
      if (!content) return;
      if (role === "user" && compactText(content) === lastUserTranscript) return;
      if (role === "assistant" && compactText(content) === lastAssistantTranscript) return;
      appendLogEntry("tool", prettifyLogRole(role), content);
    },
    onCameraImage: (params) => {
      const imageB64 = params?.image_b64;
      const imageUrl = params?.image_url;
      if (!imageB64 && !imageUrl) return;
      const mimeType = validImageMimeType(params?.mime_type);
      cameraImage.src = imageUrl || `data:${mimeType};base64,${imageB64}`;
      cameraTitle.textContent = params?.title || "Current Image";
      cameraPane.hidden = false;
      cameraStatus.textContent = timestamp();
      appendLogEntry("tool", imageUrl ? "Image" : "Camera", imageUrl ? "Displayed image." : "Captured camera image.");
    },
  });

  function cleanup() {
    subscription?.close();
    orb.dispose();
    if (defaultAction) {
      defaultAction.hidden = true;
      defaultAction.removeEventListener("click", onSetDefault);
    }
  }

  function restingState() {
    return muted ? ORB_STATES.MUTED : ORB_STATES.IDLE;
  }

  async function onMicTap() {
    if (!micReady || togglePending) return;
    togglePending = true;
    try {
      const data = await setMicMuted(!muted);
      muted = Boolean(data?.muted);
    } catch (error) {
      if (!signal.aborted) {
        caption.textContent = `Failed to toggle the microphone: ${error?.message || error}`;
      }
      return;
    } finally {
      togglePending = false;
    }
    if (signal.aborted) return;
    orb.setState(restingState());
    // setState skips unchanged states, so set the caption explicitly
    caption.textContent = CAPTION_BY_STATE[restingState()];
    syncMicAria();
  }

  async function refreshPersonalityState() {
    const personalityState = await fetchPersonalityState();
    if (signal.aborted || personalityState == null) return;
    activePersonality = personalityState.current;
    setPersonality(personalityState.current);
    const shouldHide = personalityState.locked || personalityState.current === personalityState.startup;
    if (defaultAction) {
      defaultAction.hidden = shouldHide;
    }
  }

  async function onSetDefault() {
    if (!defaultAction || !activePersonality) return;
    defaultAction.disabled = true;
    caption.textContent = `Saving "${prettifyProfileName(activePersonality)}" as default...`;
    try {
      await applyPersonality(activePersonality, { persist: true });
      if (signal.aborted) return;
      defaultAction.hidden = true;
      caption.textContent = `"${prettifyProfileName(activePersonality)}" will be used at startup.`;
    } catch (error) {
      if (!signal.aborted) {
        caption.textContent = `Failed to save default: ${error?.message || error}`;
      }
    } finally {
      defaultAction.disabled = false;
    }
  }

  function syncMicAria() {
    if (!micReady) {
      orb.root.setAttribute("aria-pressed", "false");
      orb.root.setAttribute("aria-label", "Loading microphone state");
      return;
    }
    orb.root.setAttribute("aria-pressed", String(!muted));
    orb.root.setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
  }

  function appendLogEntry(kind, label, text) {
    const entry = h(
      "li",
      { class: "talk-log__item", dataset: { kind } },
      h(
        "div",
        { class: "talk-log__meta" },
        h("span", { class: "talk-log__label" }, label),
        h("time", { class: "talk-log__time" }, timestamp())
      ),
      h("p", { class: "talk-log__text" }, compactText(text))
    );
    logItems.appendChild(entry);
    while (logItems.childElementCount > MAX_LOG_ITEMS) {
      logItems.firstElementChild?.remove();
    }
    logItems.scrollTop = logItems.scrollHeight;
    logStatus.textContent = `${logItems.childElementCount} ${logItems.childElementCount === 1 ? "event" : "events"}`;
  }
}

async function fetchPersonalityState() {
  try {
    const data = await listPersonalities();
    const current = data?.current;
    if (!current) return null;
    return {
      current,
      startup: data?.startup || "default",
      locked: Boolean(data?.locked),
    };
  } catch {
    return null;
  }
}

function subscribeConversationEvents({ onActivity, onReady, onTranscript, onLog, onCameraImage } = {}) {
  if (typeof onActivity !== "function") {
    throw new TypeError("subscribeConversationEvents: onActivity is required");
  }

  // Activity reasons now arrive as conversation.activity notifications over the
  // /rpc WebSocket; the shared client (api.js) owns reconnection.
  const unsubscribers = [];
  unsubscribers.push(subscribe("conversation.activity", (params) => {
    const reason = (params?.reason || "").trim();
    if (reason) onActivity(reason);
  }));
  if (typeof onTranscript === "function") {
    unsubscribers.push(subscribe("conversation.transcript", onTranscript));
  }
  if (typeof onLog === "function") {
    unsubscribers.push(subscribe("conversation.log", onLog));
  }
  if (typeof onCameraImage === "function") {
    unsubscribers.push(subscribe("conversation.camera_image", onCameraImage));
  }

  // The socket connects lazily, so schedule the initial mic and orb sync.
  if (typeof onReady === "function") Promise.resolve().then(onReady);

  return {
    close() {
      for (const unsubscribe of unsubscribers) unsubscribe();
    },
  };
}

function timestamp() {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function compactText(text) {
  const value = String(text).replace(/\s+/g, " ").trim();
  return value.length <= 420 ? value : `${value.slice(0, 420)}...`;
}

function prettifyActivity(reason) {
  return reason.replaceAll("_", " ");
}

function prettifyLogRole(role) {
  if (role === "assistant") return "Output";
  if (role === "user") return "User";
  if (role === "camera") return "Camera";
  if (role === "image") return "Image";
  return "System";
}

function validImageMimeType(value) {
  return value === "image/png" || value === "image/webp" || value === "image/jpeg" ? value : "image/jpeg";
}
