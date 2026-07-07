## 关联 Issue
Fixes #1

## Sprint 1 交付清单（对照 UI_SPEC.md §9）

| 文件 | 行数 | 功能 | 验收标准 |
|------|:----:|------|----------|
| `src/ui/battle_log.py` | 234 | 战报面板 — UITextBox + 13 种事件订阅 | ✅ 15 条模拟事件消息，自动滚动，三色区分 |
| `src/ui/map_widget.py` | 379 | 地图渲染 — 4 层架构 + JSON 加载 | ✅ 渲染 map_01.json (20×15 + 10 单位) |
| `src/ui/command_panel.py` | 215 | 指令面板 — 7 种指令下拉 + 单位选择 + 坐标输入 | ✅ 菜单可展开、按钮可点击打印日志 |
| `src/ui/main_window.py` | 243 | 主窗口 — 三面板组装 + 主循环 | ✅ 替换 Phase 0 骨架，28%/72%/80px 布局 |
| `src/main.py` | 精简至 38 | 入口 — 委托 MainWindow | ✅ 日志配置 + 一行启动 |
| `UI_SPEC.md` | 764 | #4 UI 层技术规格说明书 | ✅ |

## 规范合规

- ✅ WORKFLOW.md §5.3 — 仅写入 `src/ui/`，不碰 `src/core/`
- ✅ WORKFLOW.md §5.1 规则 3 — 只订阅 EventBus + 查询接口，不读写游戏数据
- ✅ STYLE_GUIDE.md §6 — 类结构 `# ── 分组 ──` 分隔
- ✅ STYLE_GUIDE.md §3 — 所有公开方法完整类型注解 + Google docstring
- ✅ 30/30 Phase 0 测试无回归

## 运行方式
```bash
pip install -r requirements.txt
python -m src.main
```

## 自检清单
- [x] 本地运行无报错
- [x] 地图加载 20×15 + 10 单位
- [x] 战报面板滚动显示 15 条消息
- [x] 指令面板按钮可交互
- [x] 通过 pytest 30 项测试
- [x] 无跨层 import
- [x] 对照 UI_SPEC.md 逐项检查完成（30/35 通过，5 项为 Sprint 2 范畴）
