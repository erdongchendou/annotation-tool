#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import copy
import json
import mimetypes
import os
import re
import threading
import uuid
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, quote, urlparse


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATE_PATH = os.path.join(BASE_DIR, ".annotation_state.json")
TASK_STATE_PATH = os.path.join(BASE_DIR, ".annotation_tasks.json")
DEFAULT_DIRECTORY = "/data01/erdong/data/mllm/key_points_verification_data/guard1211_high_priority_intermediate"
DEFAULT_OPTIONS = []
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
ZERO_WIDTH_RE = re.compile(u"[\u200B-\u200D\u2060\ufeff]")
WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalize_directory(path):
    if not path:
        return ""
    return os.path.abspath(os.path.expanduser(path))


def now_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_options(options):
    normalized = []
    seen = set()
    for option in DEFAULT_OPTIONS + list(options or []):
        text = sanitize_annotation_value(option)
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def load_state_file():
    if not os.path.exists(STATE_PATH):
        return {"directories": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"directories": {}}
    directories = data.get("directories", {})
    if not isinstance(directories, dict):
        directories = {}
    return {"directories": directories}


def load_task_state_file():
    if not os.path.exists(TASK_STATE_PATH):
        return {"tasks": {}}
    with open(TASK_STATE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"tasks": {}}
    tasks = data.get("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
    return {"tasks": tasks}


def save_json_state(state_path, state):
    temp_path = state_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, state_path)


def save_state_file(state):
    save_json_state(STATE_PATH, state)


def save_task_state_file(state):
    save_json_state(TASK_STATE_PATH, state)


def list_json_files(directory):
    files = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(".json"):
                files.append(os.path.join(root, filename))
    files.sort()
    return files


def split_file_indices(total, part_count):
    base_size = total // part_count
    remainder = total % part_count
    start = 0
    parts = []
    for index in range(part_count):
        size = base_size + (1 if index < remainder else 0)
        end = start + size
        parts.append(list(range(start, end)))
        start = end
    return parts


def extract_json_payload(text):
    value = text or ""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", value, re.S)
    payload_text = match.group(1) if match else value.strip()
    if not payload_text:
        raise ValueError("gpt 内容为空，无法解析。")
    return json.loads(payload_text, object_pairs_hook=OrderedDict)


def format_gpt_payload(payload):
    return u"```json\n%s\n```" % json.dumps(payload, ensure_ascii=False, indent=2)


def find_conversation(record, role):
    conversations = record.get("conversations", [])
    if not isinstance(conversations, list):
        return None
    for item in conversations:
        if isinstance(item, dict) and item.get("from") == role:
            return item
    return None


def resolve_image_path(record, json_path):
    stem = os.path.splitext(json_path)[0]
    for extension in IMAGE_EXTENSIONS:
        candidate = stem + extension
        if os.path.exists(candidate):
            return candidate

    images = record.get("images", [])
    if isinstance(images, list):
        for image_path in images:
            if not isinstance(image_path, str) or not image_path:
                continue
            if os.path.exists(image_path):
                return image_path
            fallback = os.path.join(os.path.dirname(json_path), os.path.basename(image_path))
            if os.path.exists(fallback):
                return fallback
    return None


def build_keypoint_list(payload):
    keypoints = payload.get("关键点", OrderedDict())
    if not isinstance(keypoints, dict):
        raise ValueError("gpt 内容中的“关键点”不是对象。")
    items = []
    for name, value in keypoints.items():
        display_name = sanitize_annotation_text(name) if isinstance(name, str) else str(name)
        items.append({"name": display_name, "value": sanitize_annotation_value(value)})
    return items


def sanitize_annotation_text(text):
    if not isinstance(text, str):
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = ZERO_WIDTH_RE.sub("", cleaned)
    cleaned = cleaned.replace(u"\u00a0", " ").replace(u"\u3000", " ")
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def sanitize_annotation_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return sanitize_annotation_text(value)
    if isinstance(value, (int, float, bool)):
        return sanitize_annotation_text(str(value))
    try:
        return sanitize_annotation_text(json.dumps(value, ensure_ascii=False))
    except Exception:
        return sanitize_annotation_text(str(value))


def stringify_annotation_value(value):
    return sanitize_annotation_value(value)


def collect_payload_options(payload):
    values = []
    overall_result = stringify_annotation_value(payload.get("判断结果", ""))
    if overall_result:
        values.append(overall_result)
    for item in build_keypoint_list(payload):
        option_value = stringify_annotation_value(item.get("value"))
        if option_value:
            values.append(option_value)
    return values


def resolve_relative_path(base_directory, relative_path):
    if not relative_path:
        raise ValueError("任务文件路径不能为空。")
    base_directory = normalize_directory(base_directory)
    candidate = os.path.abspath(os.path.join(base_directory, os.path.normpath(relative_path)))
    if candidate != base_directory and not candidate.startswith(base_directory + os.sep):
        raise ValueError("任务文件路径非法：%s" % relative_path)
    return candidate


class StateStore(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._state = load_state_file()

    def get_directory_state(self, directory):
        with self._lock:
            directories = self._state.setdefault("directories", {})
            entry = directories.get(directory, {})
            return {
                "last_index": entry.get("last_index", 0),
                "last_file": entry.get("last_file"),
                "options": normalize_options(entry.get("options", [])),
            }

    def resolve_index(self, directory, files):
        entry = self.get_directory_state(directory)
        if not files:
            return 0
        last_file = entry.get("last_file")
        if last_file in files:
            return files.index(last_file)
        last_index = entry.get("last_index", 0)
        try:
            index = int(last_index)
        except (TypeError, ValueError):
            index = 0
        return max(0, min(index, len(files) - 1))

    def get_options(self, directory):
        return self.get_directory_state(directory).get("options") or list(DEFAULT_OPTIONS)

    def update(self, directory, last_index=None, last_file=None, options=None):
        with self._lock:
            directories = self._state.setdefault("directories", {})
            entry = directories.setdefault(directory, {})
            if last_index is not None:
                entry["last_index"] = int(last_index)
            if last_file is not None:
                entry["last_file"] = last_file
            if options is not None:
                entry["options"] = normalize_options(options)
            save_state_file(self._state)


class TaskStore(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._state = load_task_state_file()

    def _get_task_entry(self, task_id):
        tasks = self._state.setdefault("tasks", {})
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            raise ValueError("任务不存在：%s" % task_id)
        task.setdefault("files", [])
        task.setdefault("options", [])
        task.setdefault("parts", [])
        task.setdefault("name", task.get("directory", task_id))
        return task

    def _get_part_entry(self, task, part_id):
        for part in task.get("parts", []):
            if isinstance(part, dict) and part.get("id") == part_id:
                part.setdefault("fileIndices", [])
                part.setdefault("name", part_id)
                part.setdefault("partIndex", 0)
                return part
        raise ValueError("子任务不存在：%s" % part_id)

    def _summarize_part(self, task, part):
        task_files = task.get("files", [])
        file_indices = []
        for raw_index in part.get("fileIndices", []):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(task_files):
                file_indices.append(index)

        file_count = len(file_indices)
        try:
            current_index = int(part.get("lastIndex", 0))
        except (TypeError, ValueError):
            current_index = 0

        if file_count:
            current_index = max(0, min(current_index, file_count - 1))
            current_relative_path = task_files[file_indices[current_index]]
            start_relative_path = task_files[file_indices[0]]
            end_relative_path = task_files[file_indices[-1]]
            current_position = current_index + 1
        else:
            current_relative_path = ""
            start_relative_path = ""
            end_relative_path = ""
            current_position = 0

        return {
            "id": part.get("id", ""),
            "name": part.get("name") or "子任务",
            "partIndex": int(part.get("partIndex", 0) or 0),
            "fileCount": file_count,
            "currentIndex": current_index,
            "currentPosition": current_position,
            "currentRelativePath": current_relative_path,
            "startRelativePath": start_relative_path,
            "endRelativePath": end_relative_path,
        }

    def _summarize_task(self, task):
        parts = [self._summarize_part(task, part) for part in task.get("parts", []) if isinstance(part, dict)]
        return {
            "id": task.get("id", ""),
            "name": task.get("name", ""),
            "directory": task.get("directory", ""),
            "total": len(task.get("files", [])),
            "createdAt": task.get("createdAt", ""),
            "updatedAt": task.get("updatedAt", ""),
            "partCount": len(parts),
            "optionsCount": len(normalize_options(task.get("options", []))),
            "parts": parts,
        }

    def _part_layout_matches(self, parts, layouts):
        if len(parts or []) != len(layouts):
            return False
        for index, layout in enumerate(layouts):
            part = parts[index]
            if not isinstance(part, dict):
                return False
            if part.get("fileIndices", []) != layout:
                return False
        return True

    def list_tasks(self):
        with self._lock:
            tasks = [task for task in self._state.setdefault("tasks", {}).values() if isinstance(task, dict)]
            tasks.sort(
                key=lambda task: (task.get("updatedAt") or task.get("createdAt") or "", task.get("id", "")),
                reverse=True,
            )
            return [self._summarize_task(task) for task in tasks]

    def import_task(self, directory, files, options):
        target_directory = normalize_directory(directory)
        relative_files = [os.path.relpath(file_path, target_directory) for file_path in files]

        with self._lock:
            tasks = self._state.setdefault("tasks", {})
            for task in tasks.values():
                if not isinstance(task, dict):
                    continue
                if task.get("directory") != target_directory:
                    continue
                existing_files = task.get("files", [])
                if existing_files != relative_files:
                    if task.get("parts"):
                        raise ValueError(
                            "该目录已经导入并切分过任务，且当前目录文件列表与任务快照不一致。"
                        )
                    task["files"] = relative_files
                task["options"] = normalize_options(list(task.get("options", [])) + list(options or []))
                task.setdefault("name", os.path.basename(target_directory.rstrip(os.sep)) or target_directory)
                task["updatedAt"] = now_timestamp()
                save_task_state_file(self._state)
                return {"created": False, "task": self._summarize_task(task)}

            timestamp = now_timestamp()
            task_id = "task-" + uuid.uuid4().hex[:8]
            task_name = os.path.basename(target_directory.rstrip(os.sep)) or target_directory
            task = {
                "id": task_id,
                "name": task_name,
                "directory": target_directory,
                "files": relative_files,
                "options": normalize_options(options),
                "parts": [],
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
            tasks[task_id] = task
            save_task_state_file(self._state)
            return {"created": True, "task": self._summarize_task(task)}

    def split_task(self, task_id, part_count):
        try:
            target_part_count = int(part_count)
        except (TypeError, ValueError):
            raise ValueError("切分份数必须是整数。")

        with self._lock:
            task = self._get_task_entry(task_id)
            total = len(task.get("files", []))
            if total <= 0:
                raise ValueError("任务中没有可切分的文件。")
            if target_part_count <= 0:
                raise ValueError("切分份数必须大于 0。")
            if target_part_count > total:
                raise ValueError("切分份数不能大于文件数量（%s）。" % total)

            layouts = split_file_indices(total, target_part_count)
            if self._part_layout_matches(task.get("parts", []), layouts):
                return {"changed": False, "task": self._summarize_task(task)}

            parts = []
            for index, file_indices in enumerate(layouts):
                first_relative_path = task["files"][file_indices[0]] if file_indices else None
                parts.append(
                    {
                        "id": "part-%s" % (index + 1),
                        "name": "第 %s / %s 份" % (index + 1, target_part_count),
                        "partIndex": index,
                        "fileIndices": file_indices,
                        "lastIndex": 0,
                        "lastFile": first_relative_path,
                    }
                )

            task["parts"] = parts
            task["updatedAt"] = now_timestamp()
            save_task_state_file(self._state)
            return {"changed": True, "task": self._summarize_task(task)}

    def delete_task(self, task_id):
        if not task_id:
            raise ValueError("任务 ID 不能为空。")

        with self._lock:
            tasks = self._state.setdefault("tasks", {})
            task = tasks.get(task_id)
            if not isinstance(task, dict):
                raise ValueError("任务不存在：%s" % task_id)

            summary = self._summarize_task(task)
            del tasks[task_id]
            save_task_state_file(self._state)
            return {"deleted": True, "task": summary}

    def get_task(self, task_id):
        with self._lock:
            return copy.deepcopy(self._get_task_entry(task_id))

    def get_options(self, task_id):
        with self._lock:
            task = self._get_task_entry(task_id)
            return normalize_options(task.get("options", []))

    def update_part_state(self, task_id, part_id, last_index=None, last_file=None, options=None):
        with self._lock:
            task = self._get_task_entry(task_id)
            part = self._get_part_entry(task, part_id)

            valid_file_indices = []
            for raw_index in part.get("fileIndices", []):
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(task.get("files", [])):
                    valid_file_indices.append(index)

            if last_index is not None:
                try:
                    safe_index = int(last_index)
                except (TypeError, ValueError):
                    safe_index = 0
                if valid_file_indices:
                    safe_index = max(0, min(safe_index, len(valid_file_indices) - 1))
                else:
                    safe_index = 0
                part["lastIndex"] = safe_index

            if last_file is not None:
                part["lastFile"] = last_file

            if options is not None:
                task["options"] = normalize_options(options)

            task["updatedAt"] = now_timestamp()
            save_task_state_file(self._state)


class AnnotationApp(object):
    def __init__(self, default_directory):
        self.default_directory = normalize_directory(default_directory) or DEFAULT_DIRECTORY
        self.state_store = StateStore()
        self.task_store = TaskStore()

    def require_directory(self, directory):
        target = normalize_directory(directory) or self.default_directory
        if not target:
            raise ValueError("目录不能为空。")
        if not os.path.isdir(target):
            raise ValueError("目录不存在：%s" % target)
        return target

    def collect_directory_options(self, directory):
        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)

        options = []
        seen = set()

        def add_option(value):
            text = stringify_annotation_value(value)
            if text and text not in seen:
                seen.add(text)
                options.append(text)

        for json_path in files:
            try:
                with open(json_path, "r", encoding="utf-8") as handle:
                    record = json.load(handle, object_pairs_hook=OrderedDict)
                gpt_item = find_conversation(record, "gpt")
                if gpt_item is None:
                    continue
                payload = extract_json_payload(gpt_item.get("value", ""))
                for option in collect_payload_options(payload):
                    add_option(option)
            except Exception:
                continue

        return options

    def list_tasks(self):
        return self.task_store.list_tasks()

    def import_task(self, directory):
        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)
        options = self.collect_directory_options(target_directory)
        return self.task_store.import_task(target_directory, files, options)

    def split_task(self, task_id, part_count):
        return self.task_store.split_task(task_id, part_count)

    def delete_task(self, task_id):
        return self.task_store.delete_task(task_id)

    def _build_item(self, directory, json_path, target_index, total, options, session_info):
        with open(json_path, "r", encoding="utf-8") as handle:
            record = json.load(handle, object_pairs_hook=OrderedDict)

        gpt_item = find_conversation(record, "gpt")
        if gpt_item is None:
            raise ValueError("文件缺少 gpt 对话：%s" % json_path)
        human_item = find_conversation(record, "human")
        payload = extract_json_payload(gpt_item.get("value", ""))

        item = {
            "directory": directory,
            "index": target_index,
            "total": total,
            "filePath": json_path,
            "relativePath": os.path.relpath(json_path, directory),
            "imageUrl": None,
            "meta": record.get("meta", {}) if isinstance(record.get("meta"), dict) else {},
            "humanPrompt": human_item.get("value", "") if isinstance(human_item, dict) else "",
            "images": record.get("images", []) if isinstance(record.get("images"), list) else [],
            "parsed": {
                "hazardName": sanitize_annotation_value(payload.get("隐患名称", "")),
                "overallResult": sanitize_annotation_value(payload.get("判断结果", "")),
                "areaCoordinates": payload.get("区域坐标", []),
                "keypoints": build_keypoint_list(payload),
            },
            "options": normalize_options(options),
        }
        item.update(session_info)

        image_path = resolve_image_path(record, json_path)
        if image_path:
            item["imageUrl"] = "/api/image?path=%s" % quote(image_path)
            item["imagePath"] = image_path
        else:
            item["imagePath"] = ""

        return item

    def _resolve_task_session(self, task_id, part_id):
        if not task_id:
            raise ValueError("任务 ID 不能为空。")
        if not part_id:
            raise ValueError("子任务 ID 不能为空。")

        task = self.task_store.get_task(task_id)
        target_part = None
        for part in task.get("parts", []):
            if isinstance(part, dict) and part.get("id") == part_id:
                target_part = part
                break
        if target_part is None:
            raise ValueError("子任务不存在：%s" % part_id)

        task_files = task.get("files", [])
        relative_files = []
        json_files = []
        for raw_index in target_part.get("fileIndices", []):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(task_files):
                relative_path = task_files[index]
                relative_files.append(relative_path)
                json_files.append(resolve_relative_path(task["directory"], relative_path))

        if not json_files:
            raise ValueError("子任务中没有可标注的文件。")

        return {
            "task": task,
            "part": target_part,
            "relativeFiles": relative_files,
            "jsonFiles": json_files,
        }

    def _resolve_task_index(self, part, relative_files):
        if not relative_files:
            return 0
        last_file = part.get("lastFile")
        if last_file in relative_files:
            return relative_files.index(last_file)
        try:
            index = int(part.get("lastIndex", 0))
        except (TypeError, ValueError):
            index = 0
        return max(0, min(index, len(relative_files) - 1))

    def _save_annotation_to_path(self, json_path, keypoints, overall_result):
        with open(json_path, "r", encoding="utf-8") as handle:
            record = json.load(handle, object_pairs_hook=OrderedDict)

        gpt_item = find_conversation(record, "gpt")
        if gpt_item is None:
            raise ValueError("文件缺少 gpt 对话：%s" % json_path)

        payload = extract_json_payload(gpt_item.get("value", ""))
        ordered_keypoints = OrderedDict()

        if isinstance(keypoints, dict):
            iterator = keypoints.items()
        else:
            iterator = []
            for item in keypoints or []:
                if isinstance(item, dict):
                    iterator.append((item.get("name"), item.get("value")))

        for name, value in iterator:
            clean_name = sanitize_annotation_text(name) if isinstance(name, str) else ""
            if not clean_name:
                continue
            ordered_keypoints[clean_name] = sanitize_annotation_value(value)

        if not ordered_keypoints:
            raise ValueError("没有可保存的关键点结果。")

        payload["关键点"] = ordered_keypoints
        payload["判断结果"] = sanitize_annotation_value(overall_result)
        gpt_item["value"] = format_gpt_payload(payload)

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def load_item(self, directory, index=None, options=None):
        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)

        if index is None:
            target_index = self.state_store.resolve_index(target_directory, files)
        else:
            target_index = max(0, min(int(index), len(files) - 1))

        current_options = normalize_options(options) if options is not None else self.state_store.get_options(target_directory)
        item = self._build_item(
            target_directory,
            files[target_index],
            target_index,
            len(files),
            current_options,
            {
                "sessionType": "directory",
                "taskId": "",
                "taskName": "",
                "partId": "",
                "partName": "",
                "partIndex": 0,
                "partCount": 0,
            },
        )

        self.state_store.update(
            target_directory,
            last_index=target_index,
            last_file=files[target_index],
            options=current_options,
        )
        return item

    def load_task_item(self, task_id, part_id, index=None):
        session = self._resolve_task_session(task_id, part_id)
        task = session["task"]
        part = session["part"]
        json_files = session["jsonFiles"]
        relative_files = session["relativeFiles"]

        if index is None:
            target_index = self._resolve_task_index(part, relative_files)
        else:
            target_index = max(0, min(int(index), len(json_files) - 1))

        options = self.task_store.get_options(task_id)
        item = self._build_item(
            task["directory"],
            json_files[target_index],
            target_index,
            len(json_files),
            options,
            {
                "sessionType": "task",
                "taskId": task.get("id", task_id),
                "taskName": task.get("name", ""),
                "partId": part.get("id", part_id),
                "partName": part.get("name", ""),
                "partIndex": int(part.get("partIndex", 0) or 0),
                "partCount": len(task.get("parts", [])),
            },
        )

        self.task_store.update_part_state(
            task_id,
            part_id,
            last_index=target_index,
            last_file=relative_files[target_index],
        )
        return item

    def update_state(self, directory, index, options, task_id="", part_id=""):
        if task_id or part_id:
            session = self._resolve_task_session(task_id, part_id)
            json_files = session["jsonFiles"]
            relative_files = session["relativeFiles"]
            target_index = max(0, min(int(index), len(json_files) - 1))
            self.task_store.update_part_state(
                task_id,
                part_id,
                last_index=target_index,
                last_file=relative_files[target_index],
                options=normalize_options(options),
            )
            return

        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)
        target_index = max(0, min(int(index), len(files) - 1))
        self.state_store.update(
            target_directory,
            last_index=target_index,
            last_file=files[target_index],
            options=normalize_options(options),
        )

    def save_annotation(
        self,
        directory,
        index,
        keypoints,
        overall_result,
        options,
        task_id="",
        part_id="",
    ):
        if task_id or part_id:
            session = self._resolve_task_session(task_id, part_id)
            json_files = session["jsonFiles"]
            relative_files = session["relativeFiles"]
            target_index = max(0, min(int(index), len(json_files) - 1))
            json_path = json_files[target_index]

            self._save_annotation_to_path(json_path, keypoints, overall_result)

            normalized_options = normalize_options(options)
            self.task_store.update_part_state(
                task_id,
                part_id,
                last_index=target_index,
                last_file=relative_files[target_index],
                options=normalized_options,
            )
            return {
                "saved": True,
                "filePath": json_path,
                "relativePath": relative_files[target_index],
                "index": target_index,
                "options": normalized_options,
            }

        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)
        target_index = max(0, min(int(index), len(files) - 1))
        json_path = files[target_index]

        self._save_annotation_to_path(json_path, keypoints, overall_result)

        normalized_options = normalize_options(options)
        self.state_store.update(
            target_directory,
            last_index=target_index,
            last_file=json_path,
            options=normalized_options,
        )
        return {
            "saved": True,
            "filePath": json_path,
            "index": target_index,
            "options": normalized_options,
        }


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AnnotationHandler(BaseHTTPRequestHandler):
    server_version = "AnnotationTool/2.0"

    @property
    def app(self):
        return self.server.app

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route == "/":
                return self._serve_static_file("tasks.html")
            if route in ("/tasks", "/tasks/"):
                return self._serve_static_file("tasks.html")
            if route in ("/annotate", "/annotate/"):
                return self._serve_static_file("index.html")
            if route.startswith("/static/"):
                relative_path = route[len("/static/") :]
                return self._serve_static_file(relative_path)
            if route == "/api/config":
                default_exists = os.path.isdir(self.app.default_directory)
                return self._send_json(
                    {
                        "defaultDirectory": self.app.default_directory,
                        "defaultDirectoryExists": default_exists,
                        "defaultOptions": list(DEFAULT_OPTIONS),
                    }
                )
            if route == "/api/tasks":
                return self._send_json({"tasks": self.app.list_tasks()})
            if route == "/api/session":
                return self._handle_session(parsed.query)
            if route == "/api/item":
                return self._handle_item(parsed.query)
            if route == "/api/image":
                return self._handle_image(parsed.query)
            return self._send_error_json(404, "未找到请求的资源。")
        except Exception as exc:
            return self._send_error_json(500, str(exc))

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/save":
                return self._handle_save()
            if parsed.path == "/api/state":
                return self._handle_state()
            if parsed.path == "/api/tasks/import":
                return self._handle_import_task()
            if parsed.path == "/api/tasks/split":
                return self._handle_split_task()
            if parsed.path == "/api/tasks/delete":
                return self._handle_delete_task()
            return self._send_error_json(404, "未找到请求的资源。")
        except Exception as exc:
            return self._send_error_json(500, str(exc))

    def _handle_session(self, query):
        params = parse_qs(query)
        task_id = params.get("taskId", [""])[0]
        part_id = params.get("partId", [""])[0]
        if task_id or part_id:
            item = self.app.load_task_item(task_id, part_id)
            return self._send_json(
                {
                    "directory": item["directory"],
                    "total": item["total"],
                    "currentIndex": item["index"],
                    "options": item.get("options", []),
                    "item": item,
                }
            )

        directory = params.get("directory", [""])[0]
        options = self.app.collect_directory_options(directory)
        item = self.app.load_item(directory, options=options)
        return self._send_json(
            {
                "directory": item["directory"],
                "total": item["total"],
                "currentIndex": item["index"],
                "options": options,
                "item": item,
            }
        )

    def _handle_item(self, query):
        params = parse_qs(query)
        index_text = params.get("index", ["0"])[0]
        task_id = params.get("taskId", [""])[0]
        part_id = params.get("partId", [""])[0]
        if task_id or part_id:
            return self._send_json(self.app.load_task_item(task_id, part_id, index=index_text))

        directory = params.get("directory", [""])[0]
        return self._send_json(self.app.load_item(directory, index=index_text))

    def _handle_state(self):
        body = self._read_json_body()
        self.app.update_state(
            body.get("directory", ""),
            body.get("index", 0),
            body.get("options", []),
            task_id=body.get("taskId", ""),
            part_id=body.get("partId", ""),
        )
        return self._send_json({"updated": True})

    def _handle_save(self):
        body = self._read_json_body()
        result = self.app.save_annotation(
            body.get("directory", ""),
            body.get("index", 0),
            body.get("keypoints", []),
            body.get("overallResult", ""),
            body.get("options", []),
            task_id=body.get("taskId", ""),
            part_id=body.get("partId", ""),
        )
        return self._send_json(result)

    def _handle_import_task(self):
        body = self._read_json_body()
        result = self.app.import_task(body.get("directory", ""))
        return self._send_json(result)

    def _handle_split_task(self):
        body = self._read_json_body()
        result = self.app.split_task(body.get("taskId", ""), body.get("partCount", 0))
        return self._send_json(result)

    def _handle_delete_task(self):
        body = self._read_json_body()
        result = self.app.delete_task(body.get("taskId", ""))
        return self._send_json(result)

    def _handle_image(self, query):
        params = parse_qs(query)
        image_path = params.get("path", [""])[0]
        if not image_path:
            return self._send_error_json(400, "图片路径不能为空。")
        if not os.path.isfile(image_path):
            return self._send_error_json(404, "图片不存在：%s" % image_path)

        content_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
        with open(image_path, "rb") as handle:
            data = handle.read()

        self.send_response(200)
        self._send_no_cache_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_static_file(self, relative_path):
        safe_path = os.path.normpath(relative_path).lstrip(os.sep)
        file_path = os.path.abspath(os.path.join(STATIC_DIR, safe_path))
        static_root = os.path.abspath(STATIC_DIR)
        if not file_path.startswith(static_root + os.sep) and file_path != os.path.join(
            static_root, "index.html"
        ):
            return self._send_error_json(403, "非法路径。")
        if not os.path.isfile(file_path):
            return self._send_error_json(404, "静态文件不存在。")

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as handle:
            data = handle.read()

        self.send_response(200)
        self._send_no_cache_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_no_cache_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_error_json(self, status, message):
        return self._send_json({"error": message}, status=status)

    def _send_no_cache_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")


def parse_args():
    parser = argparse.ArgumentParser(description="本地 JSON 标注工具")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument(
        "--directory",
        default=DEFAULT_DIRECTORY,
        help="默认打开的数据目录",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    app = AnnotationApp(args.directory)
    server = ThreadedHTTPServer((args.host, args.port), AnnotationHandler)
    server.app = app

    print("Annotation tool is running on http://%s:%s" % (args.host, args.port))
    print("Default directory: %s" % app.default_directory)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
