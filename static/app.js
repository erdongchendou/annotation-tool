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
  options: [],
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
  keypointsList: document.getElementById("keypointsList"),
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
  elements.loadButton.disabled = loading || state.sessionType === "task";
  elements.directoryInput.disabled = loading || state.sessionType === "task";
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

function cloneKeypoints(keypoints) {
  return (keypoints || []).map((item) => ({
    name: item.name,
    value: normalizeOptionValue(item.value),
  }));
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

function renderSampleMeta(item) {
  const meta = item.meta || {};
  elements.sampleTagText.textContent = joinMetaValues(meta.tag, meta.standard_hazard_name);
  elements.sampleExtraText.textContent = joinMetaValues(
    meta.hazard_or_not,
    meta.extra_content
  );
  elements.sampleMetaBar.classList.remove("hidden");
}

function formatEditableValue(value) {
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

function sanitizeEditableText(text) {
  return String(text)
    .replace(/\r\n?/g, "\n")
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/\u00A0/g, " ")
    .replace(/\u3000/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeOptionValue(value) {
  return sanitizeEditableText(formatEditableValue(value));
}

function mergeOptionValue(value) {
  const normalized = normalizeOptionValue(value);
  if (!normalized || state.options.includes(normalized)) {
    return;
  }
  state.options.push(normalized);
}

function mergeOptionValues(values) {
  (values || []).forEach((value) => {
    mergeOptionValue(value);
  });
}

function collectOptionsFromItem(item) {
  if (!item || !item.parsed) {
    return;
  }
  mergeOptionValue(item.parsed.overallResult);
  (item.parsed.keypoints || []).forEach((keypoint) => {
    mergeOptionValue(keypoint.value);
  });
}

function buildOptionChoices(currentValue, queryText) {
  const values = [];
  const seen = new Set();
  const query = normalizeOptionValue(queryText).toLowerCase();

  state.options.forEach((option) => {
    const normalized = normalizeOptionValue(option);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    if (!query || normalized.toLowerCase().includes(query)) {
      values.push(normalized);
    }
  });

  const current = normalizeOptionValue(currentValue);
  if (current && !seen.has(current) && (!query || current.toLowerCase().includes(query))) {
    values.push(current);
  }

  return values;
}

function closeAllComboboxes() {
  document.querySelectorAll(".keypoint-dropdown").forEach((dropdown) => {
    dropdown.classList.add("hidden");
  });
}

function sanitizeCurrentItemValues() {
  if (!state.item || !state.item.parsed) {
    return;
  }

  const inputElements = Array.from(document.querySelectorAll(".keypoint-input"));
  state.item.parsed.keypoints = (state.item.parsed.keypoints || []).map((item) => ({
    ...item,
    value: normalizeOptionValue(item.value),
  }));
  state.item.parsed.overallResult = normalizeOptionValue(state.item.parsed.overallResult);
  state.options = Array.from(
    new Set((state.options || []).map((option) => normalizeOptionValue(option)).filter(Boolean))
  );

  inputElements.forEach((input) => {
    input.value = normalizeOptionValue(input.value);
  });
}

function createCombobox(value, onUpdate) {
  const wrapper = document.createElement("div");
  wrapper.className = "keypoint-combobox";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "keypoint-input";
  input.value = normalizeOptionValue(value);
  input.spellcheck = false;
  input.placeholder = "点击选择或直接输入";

  const dropdown = document.createElement("div");
  dropdown.className = "keypoint-dropdown hidden";

  function commitInputValue(nextValue) {
    const normalizedValue = normalizeOptionValue(nextValue);
    input.value = normalizedValue;
    onUpdate(normalizedValue);
    mergeOptionValue(normalizedValue);
    return normalizedValue;
  }

  function renderDropdown(queryText = "") {
    const values = buildOptionChoices(input.value, queryText);
    dropdown.innerHTML = "";

    if (!values.length) {
      const empty = document.createElement("div");
      empty.className = "keypoint-option empty";
      empty.textContent = "无匹配项，可直接输入";
      dropdown.appendChild(empty);
      return;
    }

    values.forEach((optionValue) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "keypoint-option";
      option.textContent = optionValue;
      option.addEventListener("mousedown", (event) => {
        event.preventDefault();
      });
      option.addEventListener("click", () => {
        commitInputValue(optionValue);
        dropdown.classList.add("hidden");
      });
      dropdown.appendChild(option);
    });
  }

  function openDropdown() {
    closeAllComboboxes();
    renderDropdown("");
    dropdown.classList.remove("hidden");
  }

  input.addEventListener("focus", () => {
    openDropdown();
  });

  input.addEventListener("click", () => {
    openDropdown();
  });

  input.addEventListener("input", (event) => {
    const nextValue = event.target.value.replace(/[\u200B-\u200D\u2060\uFEFF]/g, "");
    if (nextValue !== event.target.value) {
      event.target.value = nextValue;
    }
    onUpdate(nextValue);
    renderDropdown(nextValue);
    dropdown.classList.remove("hidden");
  });

  input.addEventListener("change", (event) => {
    commitInputValue(event.target.value);
  });

  input.addEventListener("blur", () => {
    window.setTimeout(() => {
      commitInputValue(input.value);
      dropdown.classList.add("hidden");
    }, 120);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      dropdown.classList.add("hidden");
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      commitInputValue(input.value);
      dropdown.classList.add("hidden");
      input.blur();
    }
  });

  wrapper.appendChild(input);
  wrapper.appendChild(dropdown);
  return wrapper;
}

function appendEditableRow(labelText, value, onUpdate) {
  const row = document.createElement("div");
  row.className = "keypoint-row";

  const label = document.createElement("div");
  label.className = "keypoint-name";
  label.textContent = labelText;

  const control = document.createElement("div");
  control.className = "keypoint-control";
  control.appendChild(createCombobox(value, onUpdate));

  row.appendChild(label);
  row.appendChild(control);
  elements.keypointsList.appendChild(row);
}

function renderKeypoints() {
  elements.keypointsList.innerHTML = "";

  state.item.parsed.keypoints.forEach((item, index) => {
    appendEditableRow(item.name, item.value, (nextValue) => {
      if (
        normalizeOptionValue(state.item.parsed.keypoints[index].value) ===
        normalizeOptionValue(nextValue)
      ) {
        return;
      }
      state.item.parsed.keypoints[index].value = nextValue;
      state.dirty = true;
      refreshButtons();
    });
  });

  appendEditableRow("整体判断结果", state.item.parsed.overallResult, (nextValue) => {
    if (
      normalizeOptionValue(state.item.parsed.overallResult) === normalizeOptionValue(nextValue)
    ) {
      return;
    }
    state.item.parsed.overallResult = nextValue;
    state.dirty = true;
    refreshButtons();
  });
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

function renderItem(item) {
  state.item = {
    ...item,
    parsed: {
      ...item.parsed,
      overallResult: normalizeOptionValue(item.parsed.overallResult),
      keypoints: cloneKeypoints(item.parsed.keypoints),
    },
  };
  state.sessionType = item.sessionType || "directory";
  state.directory = item.directory;
  state.taskId = item.taskId || "";
  state.taskName = item.taskName || "";
  state.partId = item.partId || "";
  state.partName = item.partName || "";
  state.partIndex = Number.isFinite(item.partIndex) ? item.partIndex : 0;
  state.partCount = Number.isFinite(item.partCount) ? item.partCount : 0;
  state.index = item.index;
  state.total = item.total;
  state.dirty = false;

  elements.directoryInput.value = state.directory;
  elements.progressText.textContent = `第 ${state.index + 1} / ${state.total} 个文件`;
  elements.imageBasenameText.textContent = getBasename(state.item.imagePath);

  mergeOptionValues(item.options || []);
  collectOptionsFromItem(state.item);
  updateSessionChrome();
  renderImage(state.item);
  renderImagePath(state.item);
  renderSampleMeta(state.item);
  renderKeypoints();
  refreshButtons();
}

function refreshButtons() {
  elements.prevButton.disabled = state.loading || state.index <= 0;
  elements.nextButton.disabled =
    state.loading || !state.item || state.index >= state.total - 1;
  elements.saveButton.disabled = state.loading || !state.item;
  elements.loadButton.disabled = state.loading || state.sessionType === "task";
  elements.directoryInput.disabled = state.loading || state.sessionType === "task";

  if (!state.item) {
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

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

async function loadSession(directory) {
  setLoading(true);
  setMessage("", "info");
  try {
    const session =
      typeof directory === "object"
        ? directory
        : { directory: directory || elements.directoryInput.value.trim() };
    const data = await fetchJson(`/api/session?${buildSessionParams(session).toString()}`);
    state.options = [];
    mergeOptionValues(data.options || []);
    renderItem(data.item);
    setMessage("", "info");
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
    params.set("index", index);
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
  sanitizeCurrentItemValues();
  setLoading(true);
  try {
    await fetchJson("/api/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        sessionType: state.sessionType,
        directory: state.directory,
        taskId: state.taskId,
        partId: state.partId,
        index: state.index,
        keypoints: state.item.parsed.keypoints,
        overallResult: state.item.parsed.overallResult,
        options: state.options,
      }),
    });
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
    await loadSession(elements.directoryInput.value.trim());
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

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".keypoint-combobox")) {
      closeAllComboboxes();
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
  setLoading(true);
  try {
    const config = await fetchJson("/api/config");
    elements.directoryInput.value = config.defaultDirectory || "";
    registerEvents();
    const taskId = pageParams.get("taskId") || "";
    const partId = pageParams.get("partId") || "";

    if (!taskId || !partId) {
      window.location.replace("/");
      return;
    }

    state.sessionType = "task";
    state.taskId = taskId;
    state.partId = partId;
    updateSessionChrome();
    await loadSession({ taskId, partId });
  } catch (error) {
    registerEvents();
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

bootstrap();
