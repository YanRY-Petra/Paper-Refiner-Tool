# paper-refiner tool

面向 **Word `.docx`** 的「正文段落」辅助改写工具：从论文中按段落索引选取 **少量** 纯文字段落，在 **跳过表格 / 图片 / 公式 / 脚注与超链接等复杂结构** 的前提下，用 `prompts.yaml` 中的提示词调用兼容 OpenAI 的 Chat API（**每段一次 LLM**），并可写回为新文档。

> **说明**：请遵守所在学校对学位论文原创性与 AI 使用的规定；本工具不保证任何第三方检测结果，默认要求你使用 `--dry-run` 或人工核对后再保存。

**新手从零安装与排错**：请阅读 **[小白配置指南](docs/小白配置指南.md)**（分步文字说明：Python、`.env`、启动、端口占用、常见问题）。

---

## 功能概览

| 能力 | 说明 |
|------|------|
| 输入 | `.docx`（老版 `.doc` 请先在 Word 中另存为 `.docx`） |
| 段落扫描 | `paper-refiner list-doc` 列出每段 **是否可改写** 及跳过原因 |
| 跳过 | 表格内段落、含 `w:drawing`/`w:pict`、含 Office Math、超链接/脚注/批注引用、空段 |
| 样式过滤 | `config.example.yaml` 中按样式名子串跳过标题、题注、参考文献等 |
| 提示词 | `prompts.yaml` 中配置模板，占位符必须为 `{text}` |
| 批量上限 | 单次可勾选多段（默认最多 **1000** 段，`PAPER_REFINER_MAX_BATCH` 可调）；**每段单独请求 LLM**，多段时**默认最多 5 路并发**（`OPENAI_MAX_CONCURRENT`），结果仍按段落编号排序返回 |
| **Web 界面** | 上传 docx、勾选段落、选 prompt、生成改写、**逐段勾选采纳**后下载 `refined.docx` |

---

## Web 界面

1. 配置环境变量（复制示例后编辑；以下为 **gptsapi** 填写示例）：

```bash
cp .env.example .env
# 编辑 .env，确保包含：
# OPENAI_API_BASE=https://api.gptsapi.net
# OPENAI_API_KEY=<你的 API Key>
# OPENAI_MODEL=gpt-4o-mini
# 若平台支持且你想用 gpt-4o：OPENAI_MODEL=gpt-4o
```

2. 安装依赖并启动服务（**推荐**：密钥用命令行传入，不写进文件）。以下为 **gptsapi** 示例：

```bash
pip install -e .
paper-refiner-web --api-key sk-你的密钥 --api-base https://api.gptsapi.net --model gpt-4o-mini
```

使用 **gpt-4o** 时把 `--model` 改为 `gpt-4o` 即可。

**DeepSeek** 示例：

```bash
paper-refiner-web --api-key sk-你的密钥 --api-base https://api.deepseek.com --model deepseek-chat
```

仅使用 `.env` 时（与 `prompts.yaml` 同目录）：

```bash
paper-refiner-web
```

浏览器打开 **http://127.0.0.1:8765**（默认监听 `0.0.0.0:8765`，局域网内其他设备也可访问，请注意不要在公网暴露无鉴权实例）。

**`.env` 位置说明**：无论从哪个目录启动 `paper-refiner-web`，都会**优先加载仓库根目录**（与 `prompts.yaml` 同级）下的 `.env`，避免 AutoDL / systemd 等工作目录不是项目根时读不到密钥。请把 `OPENAI_API_KEY` 写在该文件中；**等号两侧不要多空格**，密钥整行粘贴、勿加引号。

3. 页面流程：上传 `.docx` → 勾选段落 → 选择 Prompt →「生成改写」→ 在「改写稿」中可编辑 → 勾选「采纳本段」→「导出已采纳段落为 docx」。每条结果会标注使用的 `prompt_id`。

会话与上传文件缓存在 `src/paper_refiner/web/_session_data/<uuid>/`；点击「重新上传」会尝试删除当前会话目录。

---

## 环境准备

需要 **Python 3.10+**。

```bash
cd paper-refiner-tool
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

复制环境变量示例并填写 API：

```bash
cp .env.example .env
# 编辑 .env：OPENAI_API_KEY、OPENAI_API_BASE（如 https://api.gptsapi.net）、OPENAI_MODEL（如 gpt-4o-mini）
```

复制过滤配置（可按需改名并修改）：

```bash
cp config.example.yaml config.yaml
```

之后命令里用 `--config config.yaml`；若不传，CLI 默认使用仓库内的 `config.example.yaml`。

---

## 使用教程

### 1. 查看所有段落与跳过原因

```bash
paper-refiner list-doc ./你的论文.docx --config ./config.yaml
```

只显示 **可改写** 段落（仍显示全局索引，与 Word 中顺序一致需自行对照）：

```bash
paper-refiner list-doc ./你的论文.docx --config ./config.yaml --eligible-only
```

输出中 `OK` 表示该段通过结构 + 样式检查，可被 `rewrite` 选中。

### 2. 查看已配置的 prompt id

```bash
paper-refiner prompts
```

### 3. 先 dry-run（强烈推荐）

对段落索引 `12`（示例）试运行，**不写文件**：

```bash
paper-refiner rewrite ./你的论文.docx \
  --indices 12 \
  --prompt-id non_native_english \
  --config ./config.yaml \
  --dry-run
```

多段（不超过默认上限 1000，每段单独调用 LLM）：

```bash
paper-refiner rewrite ./你的论文.docx \
  --indices 12,13 \
  --prompt-id non_native_english \
  --config ./config.yaml \
  --dry-run
```

### 4. 写回新 docx

```bash
paper-refiner rewrite ./你的论文.docx \
  --indices 12 \
  --prompt-id non_native_english \
  --config ./config.yaml \
  --output ./你的论文_润色片段.docx
```

**务必保留原始文件**；建议每改一小部分另存为新文件名。

### 5. 自定义 prompts

编辑项目根目录 `prompts.yaml`：

- 每条需包含 `id`、`name`、`template`
- `template` 中必须包含字面量 `{text}`，运行时会替换为当前段落全文

### 6. 自定义样式过滤

编辑 `config.yaml`（由 `config.example.yaml` 复制）：

- `skip_style_substrings`：样式名 **包含** 任一子串（不区分大小写）则跳过  
- `body_style_substrings`：若列表 **非空**，则仅当样式名包含其中任一子串时才允许改写（用于模板里「正文」样式名很明确的场景）

---

## 项目结构

```
paper-refiner-tool/
  pyproject.toml
  requirements.txt
  prompts.yaml              # LLM 模板
  config.example.yaml       # 样式过滤示例
  src/paper_refiner/
    paths.py                # 仓库根路径
    cli.py                  # Typer 命令行
    scan.py                 # 段落扫描与资格判定
    xmlutil.py              # 表格/图/公式等 OOXML 检测
    apply.py                # 写回纯文字段
    llm.py                  # OpenAI 兼容 Chat API
    config_loader.py        # YAML 加载
    web/
      app.py                # FastAPI 应用与 REST API
      run.py                # uvicorn 启动入口
      sessions.py           # 上传会话（临时目录）
      templates/index.html
      static/style.css, app.js
  README.md
  LICENSE
```

---

## 常见问题

**Q：点击「生成改写」出现 401 / invalid api key？**  
A：表示 **服务商拒绝了当前密钥**（无效、过期、复制不全或与 Base URL 不匹配）。请在 DeepSeek 控制台复制完整 `sk-…`，使用命令行 `--api-key` 或写入 `.env` 的 `OPENAI_API_KEY`（或 `DEEPSEEK_API_KEY`），并保证 `OPENAI_API_BASE=https://api.deepseek.com`（程序会自动补 `/v1`）；**修改环境变量后必须重启** `paper-refiner-web`。

**Q：点击「生成改写」出现 500 / Internal Server Error？**  
A：常见原因已处理或会显示为可读错误：（1）论文段落里含 `{` `}` 时，旧版用 `str.format` 会崩溃，现已改为安全插入；（2）未配置 `OPENAI_API_KEY` 或 API 地址/密钥错误——现在会返回 **503/502** 并在页面上显示简要原因（请检查服务器上的 `.env`）。

**Q：表格里的字会出现在列表里吗？**  
A：当前基于 `python-docx` 的 `document.paragraphs`，它只覆盖 **正文流里直接的 `w:p`**，**不会**列出表格单元格内的段落，因此工具也 **不会改写表内文字**（等价于整表跳过）。若以后需要支持表内说明文字，需要额外遍历 `document.tables` 再套同一套安全规则。

**Q：公式在单独一行也会被跳过吗？**  
A：若该段 OOXML 中含 `m:oMath` / `m:oMathPara`，会标记为 `formula/math` 并跳过。

**Q：能否保证知网 AIGC 率一定下降？**  
A：不能。检测模型与论文领域都会变；本仓库仅提供技术流水线。

---

## 开源与责任

发布到 GitHub 时建议在 README 显著位置重申：用户需自担学术合规责任；勿将含有隐私或未脱敏数据的论文提交至不可信第三方 API。
