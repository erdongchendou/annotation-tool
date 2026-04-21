const state = {
  tasks: [],
  loading: false,
};

const elements = {
  taskDirectoryInput: document.getElementById("taskDirectoryInput"),
  importTaskButton: document.getElementById("importTaskButton"),
  taskMessageBar: document.getElementById("taskMessageBar"),
  taskCountText: document.getElementById("taskCountText"),
  tasksEmptyState: document.getElementById("tasksEmptyState"),
  tasksList: document.getElementById("tasksList"),
};

function setMessage(message, type) {
  elements.taskMessageBar.textContent = message || "";
  elements.taskMessageBar.className = "message-bar";
  if (!message) {
    elements.taskMessageBar.classList.add("hidden");
    return;
  }
  elements.taskMessageBar.classList.add(type || "info");
}

function setLoading(loading) {
  state.loading = loading;
  elements.importTaskButton.disabled = loading;
  elements.taskDirectoryInput.disabled = loading;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function formatTimestamp(value) {
  if (!value) {
    return "未知时间";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function buildPartUrl(taskId, partId) {
  const url = new URL("/annotate", window.location.href);
  url.searchParams.set("taskId", taskId);
  url.searchParams.set("partId", partId);
  return url.toString();
}

function renderTasks() {
  elements.tasksList.innerHTML = "";
  elements.taskCountText.textContent = `${state.tasks.length} 个任务`;
  elements.tasksEmptyState.classList.toggle("hidden", state.tasks.length > 0);

  state.tasks.forEach((task) => {
    const card = document.createElement("section");
    card.className = "task-card";
    card.dataset.taskId = task.id;

    const header = document.createElement("div");
    header.className = "task-card-header";

    const titleBlock = document.createElement("div");
    titleBlock.className = "task-card-title";

    const taskName = document.createElement("div");
    taskName.className = "task-name";
    taskName.textContent = task.name || task.id;

    const taskDirectory = document.createElement("div");
    taskDirectory.className = "task-directory";
    taskDirectory.textContent = task.directory || "";

    const taskMeta = document.createElement("div");
    taskMeta.className = "task-meta";
    taskMeta.textContent = `共 ${task.total} 个 JSON，已切分 ${task.partCount} 份，更新时间 ${formatTimestamp(
      task.updatedAt
    )}`;

    titleBlock.appendChild(taskName);
    titleBlock.appendChild(taskDirectory);
    titleBlock.appendChild(taskMeta);

    const splitToolbar = document.createElement("div");
    splitToolbar.className = "split-toolbar";

    const splitLabel = document.createElement("label");
    splitLabel.htmlFor = `split-count-${task.id}`;
    splitLabel.textContent = "切分份数";

    const splitInput = document.createElement("input");
    splitInput.id = `split-count-${task.id}`;
    splitInput.type = "number";
    splitInput.min = "1";
    splitInput.max = String(Math.max(1, task.total || 1));
    splitInput.value = String(task.partCount || Math.min(3, Math.max(1, task.total || 1)));
    splitInput.dataset.partCountFor = task.id;

    const splitButton = document.createElement("button");
    splitButton.type = "button";
    splitButton.className = "primary split-task-button";
    splitButton.dataset.action = "split";
    splitButton.dataset.taskId = task.id;
    splitButton.textContent = "切分任务";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger delete-task-button";
    deleteButton.dataset.action = "delete-task";
    deleteButton.dataset.taskId = task.id;
    deleteButton.textContent = "删除任务";

    splitToolbar.appendChild(splitLabel);
    splitToolbar.appendChild(splitInput);
    splitToolbar.appendChild(splitButton);
    splitToolbar.appendChild(deleteButton);

    header.appendChild(titleBlock);
    header.appendChild(splitToolbar);
    card.appendChild(header);

    if (!task.parts || !task.parts.length) {
      const emptyState = document.createElement("div");
      emptyState.className = "empty-state";
      emptyState.textContent = "还没有子任务。输入份数后点击“切分任务”。";
      card.appendChild(emptyState);
      elements.tasksList.appendChild(card);
      return;
    }

    const partsGrid = document.createElement("div");
    partsGrid.className = "parts-grid";

    task.parts.forEach((part) => {
      const partCard = document.createElement("div");
      partCard.className = "part-card";

      const partName = document.createElement("div");
      partName.className = "part-name";
      partName.textContent = part.name || part.id;

      const partMeta = document.createElement("div");
      partMeta.className = "part-meta";
      partMeta.textContent = `共 ${part.fileCount} 个文件，当前位置 ${part.currentPosition}/${part.fileCount}`;

      const partUrl = buildPartUrl(task.id, part.id);

      const partLinkRow = document.createElement("div");
      partLinkRow.className = "part-link-row";

      const partLinkInput = document.createElement("input");
      partLinkInput.className = "part-link-input";
      partLinkInput.type = "text";
      partLinkInput.readOnly = true;
      partLinkInput.value = partUrl;

      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.dataset.action = "copy-link";
      copyButton.dataset.link = partUrl;
      copyButton.textContent = "复制链接";

      const openLink = document.createElement("a");
      openLink.className = "nav-link";
      openLink.href = partUrl;
      openLink.target = "_blank";
      openLink.rel = "noreferrer";
      openLink.textContent = "打开标注页";

      partLinkRow.appendChild(partLinkInput);
      partLinkRow.appendChild(copyButton);
      partLinkRow.appendChild(openLink);

      partCard.appendChild(partName);
      partCard.appendChild(partMeta);
      partCard.appendChild(partLinkRow);
      partsGrid.appendChild(partCard);
    });

    card.appendChild(partsGrid);
    elements.tasksList.appendChild(card);
  });
}

async function loadTasks() {
  const data = await fetchJson("/api/tasks");
  state.tasks = data.tasks || [];
  renderTasks();
}

async function importTask() {
  if (state.loading) {
    return;
  }

  const directory = elements.taskDirectoryInput.value.trim();
  if (!directory) {
    setMessage("请先输入要导入的目录。", "error");
    return;
  }

  setLoading(true);
  setMessage("", "info");
  try {
    const result = await fetchJson("/api/tasks/import", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ directory }),
    });
    await loadTasks();
    setMessage(
      result.created
        ? `任务已导入：${result.task.name}`
        : `该目录已存在任务，已复用：${result.task.name}`,
      "success"
    );
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

async function splitTask(taskId, partCount) {
  if (state.loading) {
    return;
  }

  setLoading(true);
  setMessage("", "info");
  try {
    const result = await fetchJson("/api/tasks/split", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        taskId,
        partCount,
      }),
    });
    await loadTasks();
    setMessage(
      result.changed
        ? `任务已切分：${result.task.name}`
        : `该切分结果已存在：${result.task.name}`,
      "success"
    );
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

async function deleteTask(taskId) {
  if (state.loading || !taskId) {
    return;
  }

  const task = state.tasks.find((item) => item.id === taskId);
  const taskName = (task && task.name) || taskId;
  const confirmed = window.confirm(`确定删除任务“${taskName}”吗？`);
  if (!confirmed) {
    return;
  }

  setLoading(true);
  setMessage("", "info");
  try {
    const result = await fetchJson("/api/tasks/delete", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ taskId }),
    });
    await loadTasks();
    setMessage(`任务已删除：${result.task.name || taskId}`, "success");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

async function copyLink(link) {
  try {
    await navigator.clipboard.writeText(link);
    setMessage("子任务链接已复制。", "success");
  } catch (error) {
    window.prompt("复制下面的子任务链接：", link);
  }
}

function registerEvents() {
  elements.importTaskButton.addEventListener("click", async () => {
    await importTask();
  });

  elements.taskDirectoryInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      await importTask();
    }
  });

  elements.tasksList.addEventListener("click", async (event) => {
    const splitButton = event.target.closest("[data-action='split']");
    if (splitButton) {
      const taskId = splitButton.dataset.taskId;
      const input = elements.tasksList.querySelector(`[data-part-count-for="${taskId}"]`);
      if (!input) {
        return;
      }
      await splitTask(taskId, input.value);
      return;
    }

    const deleteButton = event.target.closest("[data-action='delete-task']");
    if (deleteButton) {
      await deleteTask(deleteButton.dataset.taskId || "");
      return;
    }

    const copyButton = event.target.closest("[data-action='copy-link']");
    if (copyButton) {
      await copyLink(copyButton.dataset.link || "");
    }
  });
}

async function bootstrap() {
  setLoading(true);
  try {
    registerEvents();
    await loadTasks();
  } catch (error) {
    registerEvents();
    setMessage(error.message, "error");
  } finally {
    setLoading(false);
  }
}

bootstrap();
