# BlindCommand 技术栈

> **版本**: v1.0 | **定稿日期**: 2026-07-07 | **全员必须遵守**

---

## 总览

| 层次 | 选型 | 版本 | 用途 |
|------|------|:----:|------|
| **语言** | Python | 3.11.x | 主开发语言 |
| **游戏框架** | pygame-ce | ≥2.5, <3.0 | 地图渲染、精灵、鼠标事件（Community Edition，与 pygame 完全兼容，`import pygame` 不变） |
| **UI 组件** | pygame_gui | ≥0.6.10, <0.7 | 战报面板、下拉菜单、按钮 |
| **格式化** | black | ≥24 | 代码风格统一 |
| **Import 排序** | isort | ≥5 | import 顺序统一 |
| **Linter** | ruff | ≥0.5 | 快速静态检查 |
| **类型检查** | mypy | ≥1.10 | strict 模式，CI 强制 |
| **测试** | pytest | ≥8 | 单元测试 + 集成测试 |
| **打包** | PyInstaller | ≥6 | 单文件 .exe 分发 |
| **版本控制** | Git + GitHub | — | 分支协作 |
| **数据格式** | JSON | — | 地图、单位配置 |
| **Python 包管理** | pip + venv | — | 虚拟环境隔离 |

---

## 为什么选 Pygame + pygame_gui？

```
需求分析：
  2D 瓦片地图渲染 ──▶ pygame.Surface.blit() 天然适合
  鼠标拖拽方块      ──▶ pygame 事件系统 + sprite 碰撞检测
  左侧滚动战报      ──▶ pygame_gui.UITextBox（自带滚动条）
  底部指令按钮      ──▶ pygame_gui.UIButton + UIDropDownMenu
  Vibe Coding      ──▶ AI 对 pygame 代码生成质量是所有游戏框架中最高的

不选 PyQt 的原因：
  - AI 生成的 Qt 代码 bug 率明显高于 pygame
  - Qt 信号/槽虽好但学习曲线陡，五人上手成本高
  - GPL 协议对开源项目有约束（虽可 LGPL 但心智负担大）
```

---

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS / Linux

# 2. 安装运行依赖
pip install -r requirements.txt

# 3. 安装开发依赖（全员必须）
pip install -r requirements-dev.txt

# 4. 安装 pre-commit hooks
pre-commit install

# 5. 运行游戏
python -m src.main

# 6. 运行测试
pytest tests/ -v

# 7. 类型检查
mypy src/

# 8. 格式化代码
black src/ tests/
isort src/ tests/

# 9. 打包
pyinstaller BlindCommand.spec
```

---

## 五人分工与文件对应

| 角色 | 操作的文件 | 导出的包 |
|:----:|-----------|----------|
| #2 底层 | `src/core/` (除 constants.py) | `from src.core import ...` |
| #3 业务 | `src/battle/` | `from src.battle import ...` |
| #4 UI | `src/ui/` | `from src.ui import ...` |
| #5 工程 | `pyproject.toml` `requirements*.txt` `.pre-commit-config.yaml` `.gitignore` `data/` `src/ui/assets/` | — |
| 全员只读 | `src/core/constants.py` | 修改必须 PR + Review |

---

## pre-commit 自动化流程

每次 `git commit` 自动执行（约 3-5 秒）：

```
1. black   → 格式化代码（行宽 100）
2. isort   → 排序 import
3. ruff    → lint 检查 + 自动修复
4. 通用检查 → 行尾空格、文件末尾换行、合并冲突标记、debug 语句
```

如果任一检查失败，commit 被阻止。修复后重新 commit 即可。

> **注意**：mypy 不在 pre-commit 中（太慢，5-15 秒），在 CI 中单独运行。

---

## CI / GitHub Actions（#5 搭建，后续补充）

```
push / PR →
  1. checkout
  2. setup Python 3.11
  3. pip install -r requirements-dev.txt
  4. black --check .        ← 格式化检查
  5. isort --check-only .   ← import 检查
  6. ruff check .           ← lint
  7. mypy src/              ← 类型检查（strict）
  8. pytest tests/ -v       ← 测试
```

全部通过才允许合并。

---

## 常见问题

### Q: 为什么不用 pygame 的 sprite.Group？
可以用。`pygame.sprite.Sprite` 适合需要碰撞检测和分层渲染的场景。单位方块和标记方块都可以继承 Sprite。但单位**数据逻辑**（血量、坐标、属性）必须与 Sprite 分离——数据归 #2/#3，Sprite 归 #4。

### Q: pygame_gui 的 UITextBox 能实时追加战报吗？
可以。`UITextBox.append_html_text()` 支持逐条追加消息，自动滚动到底部。战报消息用 HTML 标记颜色（红=危险、金=重要、白=普通）。

### Q: mypy strict 模式会不会太严格？
Vibe Coding 下 AI 生成的跨模块调用容易出现参数类型不匹配。strict 模式在 CI 中能拦截这些问题。如果某处确实需要宽松类型，用 `# type: ignore[reason]` 显式标注即可。

### Q: 为什么锁定 Python 3.11 而不是 3.12/3.13？
PyInstaller 对新 Python 版本适配有滞后。3.11 是当前生态兼容性最好的版本，各平台仓库默认版本。
