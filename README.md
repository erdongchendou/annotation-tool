# JSON 标注工具

本地网页标注工具，支持打开任意目录并遍历其中全部 JSON 文件，对 `gpt` 对话中的 `关键点` 和 `判断结果` 进行覆盖式保存。

## 启动

```bash
cd /data01/erdong/data/mllm/key_points_verification_data/annotation_tool_web
python3 server.py --host 127.0.0.1 --port 8000
```

默认会打开：

```text
/data01/erdong/data/mllm/key_points_verification_data/guard1211_high_priority_intermediate
```

也可以显式指定目录：

```bash
python3 server.py --directory /your/json/root
```

如果需要让其他机器访问：

```bash
python3 server.py --host 0.0.0.0 --port 8000
```

## 访问方式

- 如果你是直接从自己电脑浏览器访问服务器，使用 `http://服务器IP:端口`，例如 `http://10.1.9.58:8001`
- 如果你是通过 SSH 端口转发访问，才使用 `http://127.0.0.1:8001`
- `127.0.0.1` 永远指当前打开浏览器的那台机器，不是远端服务器

## 目录说明

- 工具里的“数据目录”必须是服务器本机上的真实路径
- 如果默认目录在当前服务器不存在，页面会提示你手动输入目录，不会再直接报错
- 图片优先读取 `JSON` 同目录下的同名图片；如果没有，再回退到 JSON 里的 `images` 路径

## 功能

- 按完整路径字典序遍历目录下所有 JSON
- 左侧显示图片，右侧显示 `meta`、隐患名称、整体判断、关键点、区域坐标和原始提问
- 支持给所有关键点统一新增自定义选项
- 点击“保存”“上一个”“下一个”时会自动保存当前文件
- 关闭页面后再次打开，会回到上次标注到的文件

## 状态文件

工具会在项目目录下维护一个本地状态文件：

```text
annotation_tool_web/.annotation_state.json
```

它只保存每个目录的最近位置和可选项，不改动你的原始目录结构。
