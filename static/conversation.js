const pageParams = new URLSearchParams(window.location.search);

const state = {
  sessionType: "directory",
  directory: "",
  taskId: "",
  taskName: "",
  partId: "",
  partName: "",
  partIndex: 0,
  partCount: 0,
  index: 0,
  total: 0,
  item: null,
  dirty: false,
  loading: false,
};

const elements = {
  directoryPanel: document.getElementById("directoryPanel"),
  directoryInput: document.getElementById("directoryInput"),
  loadButton: document.getElementById("loadButton"),
  taskSessionPanel: document.getElementById("taskSessionPanel"),
  taskSessionTitle: document.getElementById("taskSessionTitle"),
  taskSessionSubtitle: document.getElementById("taskSessionSubtitle"),
  prevButton: document.getElementById("prevButton"),
  saveButton: document.getElementById("saveButton"),
  nextButton: document.getElementById("nextButton"),
  progressText: document.getElementById("progressText"),
  previewImage: document.getElementById("previewImage"),
  imagePlaceholder: document.getElementById("imagePlaceholder"),
  sampleMetaBar: document.getElementById("sampleMetaBar"),
  sampleTagText: document.getElementById("sampleTagText"),
  sampleExtraText: document.getElementById("sampleExtraText"),
  imageBasenameText: document.getElementById("imageBasenameText"),
  imagePathText: document.getElementById("imagePathText"),
  conversationPairs: document.getElementById("conversationPairs"),
  messageBar: document.getElementById("messageBar"),
};

function setMessage(message, type) {
  elements.messageBar.textContent = message || "";
  elements.messageBar.className = "message-bar";
  if (!message) {
    elements.messageBar.classList.add("hidden");
    return;
  }
  elements.messageBar.classList.add(type || "info");
}

function setLoading(loading) {
  state.loading = loading;
  elements.directoryInput.disabled = loading || state.sessionType === "task";
  elements.loadButton.disabled = loading || state.sessionType === "task";
  elements.prevButton.disabled = loading || state.index <= 0;
  elements.saveButton.disabled = loading || !state.item;
  elements.nextButton.disabled = loading || !state.item || state.index >= state.total - 1;
}

function hasTaskContext(session = {}) {
  const taskId =
    typeof session.taskId === "string" ? session.taskId : state.taskId;
  const partId =
    typeof session.partId === "string" ? session.partId : state.partId;
  return Boolean(taskId || partId);
}

function buildSessionParams(session = {}) {
  const params = new URLSearchParams();

  if (hasTaskContext(session)) {
    const taskId =
      typeof session.taskId === "string" ? session.taskId : state.taskId;
    const partId =
      typeof session.partId === "string" ? session.partId : state.partId;
    params.set("taskId", taskId);
    params.set("partId", partId);
    return params;
  }

  const directory =
    typeof session.directory === "string" ? session.directory : state.directory;
  params.set("directory", directory);
  return params;
}

function updateSessionChrome() {
  const taskMode = state.sessionType === "task";
  elements.directoryPanel.classList.toggle("hidden", taskMode);
  elements.taskSessionPanel.classList.toggle("hidden", !taskMode);

  if (!taskMode) {
    elements.taskSessionTitle.textContent = "";
    elements.taskSessionSubtitle.textContent = "";
    return;
  }

  const titleParts = [state.taskName, state.partName].filter(Boolean);
  elements.taskSessionTitle.textContent = titleParts.join(" ");
  elements.taskSessionSubtitle.textContent = state.directory || "";
}

function maybeRedirectTaskPage(item) {
  if (!item || item.sessionType !== "task" || item.taskType !== "key_points") {
    return false;
  }

  const url = new URL("/annotate", window.location.href);
  url.searchParams.set("taskId", item.taskId || state.taskId || "");
  url.searchParams.set("partId", item.partId || state.partId || "");
  if (window.location.pathname === "/annotate") {
    return false;
  }
  window.location.replace(url.toString());
  return true;
}

function fetchJson(url, options) {
  return fetch(url, options).then(async (response) => {
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "请求失败");
    }
    return data;
  });
}

function joinMetaValues(...values) {
  const parts = values
    .map((value) => (value === null || value === undefined ? "" : String(value).trim()))
    .filter(Boolean);
  return parts.join(" ") || "未提供";
}

function getBasename(path) {
  const value = typeof path === "string" ? path : "";
  if (!value) {
    return "";
  }
  const segments = value.split(/[\\/]/);
  return segments[segments.length - 1] || "";
}

function sanitizeConversationText(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(/\r\n?/g, "\n")
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/\u00A0/g, " ")
    .replace(/\u3000/g, " ")
    .trim();
}

function formatConversationValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch (error) {
    return String(value);
  }
}

function cloneConversationPairs(pairs) {
  const nextPairs = (pairs || []).slice(0, 3).map((pair) => ({
    question: sanitizeConversationText(formatConversationValue(pair && pair.question)),
    answer: sanitizeConversationText(formatConversationValue(pair && pair.answer)),
  }));

  while (nextPairs.length < 3) {
    nextPairs.push({ question: "", answer: "" });
  }

  return nextPairs;
}

function sanitizeCurrentConversationPairs() {
  if (!state.item) {
    return;
  }
  state.item.conversationPairs = cloneConversationPairs(state.item.conversationPairs);
  document.querySelectorAll(".qa-input").forEach((input) => {
    const pairIndex = Number(input.dataset.pairIndex);
    const field = input.dataset.field;
    if (!Number.isInteger(pairIndex) || !field) {
      return;
    }
    input.value = state.item.conversationPairs[pairIndex][field];
  });
}

function renderSampleMeta(item) {
  const meta = item.meta || {};
  elements.sampleTagText.textContent = joinMetaValues(meta.tag, meta.standard_hazard_name);
  elements.sampleExtraText.textContent = joinMetaValues(
    meta.hazard_or_not,
    meta.extra_content
  );
  elements.sampleMetaBar.classList.remove("hidden");
}

function renderImage(item) {
  if (item.imageUrl) {
    elements.previewImage.src = item.imageUrl;
    elements.previewImage.classList.remove("hidden");
    elements.imagePlaceholder.classList.add("hidden");
  } else {
    elements.previewImage.removeAttribute("src");
    elements.previewImage.classList.add("hidden");
    elements.imagePlaceholder.classList.remove("hidden");
  }
}

function renderImagePath(item) {
  elements.imagePathText.textContent = item.imagePath || "当前样本没有可显示的图片路径";
}

function updatePairField(index, field, value) {
  if (!state.item || !state.item.conversationPairs[index]) {
    return;
  }
  if (state.item.conversationPairs[index][field] === value) {
    return;
  }
  state.item.conversationPairs[index][field] = value;
  state.dirty = true;
  refreshButtons();
}

function createPairInput(index, field, label, placeholder, value) {
  const fieldBlock = document.createElement("label");
  fieldBlock.className = "qa-field";

  const caption = document.createElement("span");
  caption.className = "qa-label";
  caption.textContent = label;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "qa-input";
  input.dataset.pairIndex = String(index);
  input.dataset.field = field;
  input.placeholder = placeholder;
  input.value = value;
  input.spellcheck = false;
  input.addEventListener("input", (event) => {
    updatePairField(index, field, event.target.value);
  });
  input.addEventListener("blur", (event) => {
    const sanitized = sanitizeConversationText(event.target.value);
    event.target.value = sanitized;
    updatePairField(index, field, sanitized);
  });

  fieldBlock.appendChild(caption);
  fieldBlock.appendChild(input);
  return fieldBlock;
}

function renderConversationPairs() {
  elements.conversationPairs.innerHTML = "";

  state.item.conversationPairs.forEach((pair, index) => {
    const card = document.createElement("section");
    card.className = "qa-pair-card";

    const header = document.createElement("div");
    header.className = "qa-pair-header";
    header.textContent = `第 ${index + 1} 组`;

    card.appendChild(header);
    card.appendChild(
      createPairInput(index, "question", "问题", "问题可留空", pair.question || "")
    );
    card.appendChild(
      createPairInput(index, "answer", "回答", "填写后会保存这一轮对话", pair.answer || "")
    );

    elements.conversationPairs.appendChild(card);
  });
}

function renderItem(item) {
  if (maybeRedirectTaskPage(item)) {
    return;
  }

  state.item = {
    ...item,
    conversationPairs: cloneConversationPairs(item.conversationPairs),
  };
  state.sessionType = item.sessionType || "directory";
  state.directory = item.directory || "";
  state.taskId = item.taskId || "";
  state.taskName = item.taskName || "";
  state.partId = item.partId || "";
  state.partName = item.partName || "";
  state.partIndex = Number.isFinite(item.partIndex) ? item.partIndex : 0;
  state.partCount = Number.isFinite(item.partCount) ? item.partCount : 0;
  state.index = item.index || 0;
  state.total = item.total || 0;
  state.dirty = false;

  elements.directoryInput.value = state.directory;
  elements.imageBasenameText.textContent = getBasename(state.item.imagePath);

  updateSessionChrome();
  renderImage(state.item);
  renderImagePath(state.item);
  renderSampleMeta(state.item);
  renderConversationPairs();
  refreshButtons();
}

function refreshButtons() {
  elements.prevButton.disabled = state.loading || state.index <= 0;
  elements.nextButton.disabled = state.loading || !state.item || state.index >= state.total - 1;
  elements.saveButton.disabled = state.loading || !state.item;
  elements.loadButton.disabled = state.loading || state.sessionType === "task";
  elements.directoryInput.disabled = state.loading || state.sessionType === "task";

  if (!state.item) {
    elements.progressText.textContent = "未加载目录";
    return;
  }

  const sessionSuffix =
    state.sessionType === "task" && state.partName ? ` | ${state.partName}` : "";
  if (state.dirty) {
    elements.progressText.textContent = `第 ${state.index + 1} / ${state.total} 个文件（有未保存修改）${sessionSuffix}`;
  } else {
    elements.progressText.textContent = `第 ${state.index + 1} / ${state.total} 个文件${sessionSuffix}`;
  }
}

async function loadSession(directory) {
  const session =
    typeof directory === "object"
      ? directory
      : { directory: typeof directory === "string" ? directory.trim() : "" };
  if (!hasTaskContext(session) && !session.directory) {
    setMessage("请先输入要遍历的目录。", "error");
    return;
  }

  setLoading(true);
  setMessage("", "info");
  try {
    const params = buildSessionParams(session).toString();
    const url = hasTaskContext(session) ? `/api/session?${params}` : `/api/conversations/session?${params}`;
    const data = await fetchJson(url);
    renderItem(data.item);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

async function loadItem(index) {
  if (state.sessionType === "task" && (!state.taskId || !state.partId)) {
    return;
  }
  if (state.sessionType !== "task" && !state.directory) {
    return;
  }
  setLoading(true);
  try {
    const params = buildSessionParams();
    params.set("index", String(index));
    const item = await fetchJson(`/api/item?${params.toString()}`);
    renderItem(item);
    setMessage("", "info");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

async function saveCurrent(showMessage = true) {
  if (!state.item) {
    return false;
  }

  sanitizeCurrentConversationPairs();
  setLoading(true);
  try {
    const result = await fetchJson("/api/conversations/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        directory: state.directory,
        taskId: state.taskId,
        partId: state.partId,
        index: state.index,
        conversationPairs: state.item.conversationPairs,
      }),
    });
    if (result.conversationPairs) {
      state.item.conversationPairs = cloneConversationPairs(result.conversationPairs);
      renderConversationPairs();
    }
    state.dirty = false;
    refreshButtons();
    if (showMessage) {
      setMessage("当前文件已保存。", "success");
    }
    return true;
  } catch (error) {
    setMessage(error.message, "error");
    return false;
  } finally {
    setLoading(false);
  }
}

async function navigate(offset) {
  if (!state.item) {
    return;
  }

  const nextIndex = state.index + offset;
  if (nextIndex < 0 || nextIndex >= state.total) {
    return;
  }

  const saved = await saveCurrent(false);
  if (!saved) {
    return;
  }
  await loadItem(nextIndex);
}

async function confirmDirectorySwitch() {
  if (!state.item || !state.dirty) {
    return true;
  }
  return window.confirm("当前文件有未保存修改。切换目录前是否先保存？");
}

function registerEvents() {
  elements.previewImage.addEventListener("error", () => {
    elements.previewImage.removeAttribute("src");
    elements.previewImage.classList.add("hidden");
    elements.imagePlaceholder.classList.remove("hidden");
  });

  elements.loadButton.addEventListener("click", async () => {
    const canContinue = await confirmDirectorySwitch();
    if (!canContinue) {
      return;
    }
    if (state.item && state.dirty) {
      const saved = await saveCurrent(false);
      if (!saved) {
        return;
      }
    }
    await loadSession(elements.directoryInput.value);
  });

  elements.saveButton.addEventListener("click", async () => {
    await saveCurrent(true);
  });

  elements.prevButton.addEventListener("click", async () => {
    await navigate(-1);
  });

  elements.nextButton.addEventListener("click", async () => {
    await navigate(1);
  });

  elements.directoryInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      elements.loadButton.click();
    }
  });

  document.addEventListener("keydown", async (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      await saveCurrent(true);
      return;
    }

    if (event.target && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) {
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      await navigate(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      await navigate(1);
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) {
      return;
    }
    event.preventDefault();
    event.returnValue = "";
  });
}

async function bootstrap() {
  registerEvents();
  refreshButtons();

  const taskId = pageParams.get("taskId") || "";
  const partId = pageParams.get("partId") || "";
  if (taskId && partId) {
    state.sessionType = "task";
    state.taskId = taskId;
    state.partId = partId;
    updateSessionChrome();
    await loadSession({ taskId, partId });
    return;
  }

  const directory = pageParams.get("directory") || "";
  if (!directory) {
    return;
  }

  elements.directoryInput.value = directory;
  await loadSession(directory);
}

bootstrap();
