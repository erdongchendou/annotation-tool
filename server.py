#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import mimetypes
import os
import re
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, quote, urlparse


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATE_PATH = os.path.join(BASE_DIR, ".annotation_state.json")
DEFAULT_DIRECTORY = os.path.abspath(
    os.path.join(BASE_DIR, "..", "guard1211_high_priority_intermediate")
)
DEFAULT_OPTIONS = []
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
ZERO_WIDTH_RE = re.compile(u"[\u200B-\u200D\u2060\ufeff]")
WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalize_directory(path):
    if not path:
        return ""
    return os.path.abspath(os.path.expanduser(path))


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
    data.setdefault("directories", {})
    return data


def save_state_file(state):
    temp_path = STATE_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, STATE_PATH)


def list_json_files(directory):
    files = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(".json"):
                files.append(os.path.join(root, filename))
    files.sort()
    return files


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


class AnnotationApp(object):
    def __init__(self, default_directory):
        self.default_directory = normalize_directory(default_directory) or DEFAULT_DIRECTORY
        self.state_store = StateStore()

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

    def load_item(self, directory, index=None):
        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)

        if index is None:
            target_index = self.state_store.resolve_index(target_directory, files)
        else:
            target_index = max(0, min(int(index), len(files) - 1))

        json_path = files[target_index]
        options = self.state_store.get_options(target_directory)
        with open(json_path, "r", encoding="utf-8") as handle:
            record = json.load(handle, object_pairs_hook=OrderedDict)

        gpt_item = find_conversation(record, "gpt")
        if gpt_item is None:
            raise ValueError("文件缺少 gpt 对话：%s" % json_path)
        human_item = find_conversation(record, "human")
        payload = extract_json_payload(gpt_item.get("value", ""))

        item = {
            "directory": target_directory,
            "index": target_index,
            "total": len(files),
            "filePath": json_path,
            "relativePath": os.path.relpath(json_path, target_directory),
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
            "options": options,
        }

        image_path = resolve_image_path(record, json_path)
        if image_path:
            item["imageUrl"] = "/api/image?path=%s" % quote(image_path)
            item["imagePath"] = image_path
        else:
            item["imagePath"] = ""

        self.state_store.update(
            target_directory,
            last_index=target_index,
            last_file=json_path,
            options=options,
        )
        return item

    def update_state(self, directory, index, options):
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

    def save_annotation(self, directory, index, keypoints, overall_result, options):
        target_directory = self.require_directory(directory)
        files = list_json_files(target_directory)
        if not files:
            raise ValueError("目录中没有找到 JSON 文件：%s" % target_directory)
        target_index = max(0, min(int(index), len(files) - 1))
        json_path = files[target_index]

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
    server_version = "AnnotationTool/1.0"

    @property
    def app(self):
        return self.server.app

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route == "/":
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
            return self._send_error_json(404, "未找到请求的资源。")
        except Exception as exc:
            return self._send_error_json(500, str(exc))

    def _handle_session(self, query):
        params = parse_qs(query)
        directory = params.get("directory", [""])[0]
        item = self.app.load_item(directory)
        options = self.app.collect_directory_options(directory)
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
        directory = params.get("directory", [""])[0]
        index_text = params.get("index", ["0"])[0]
        item = self.app.load_item(directory, index=index_text)
        return self._send_json(item)

    def _handle_state(self):
        body = self._read_json_body()
        self.app.update_state(
            body.get("directory", ""),
            body.get("index", 0),
            body.get("options", []),
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
        )
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
