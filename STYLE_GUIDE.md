# BlindCommand 代码规范

> **版本**: v1.0 | **全员必须遵守** | **#1 起草并维护**

---

## 1. 总则

- 所有代码在提交前必须通过 `black` + `isort` + `ruff` 检查
- 类型注解强制（`mypy --strict` 在 CI 中检查）
- 公开函数必须写 docstring（Google 风格）
- 优先可读性，其次性能

---

## 2. 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| 模块/文件 | `snake_case` | `event_bus.py` `unit_base.py` |
| 类 | `PascalCase` | `EventBus` `GameMap` `UnitBase` |
| 接口/抽象类 | `I` 前缀 + `PascalCase` | `IUnit` `IMap` `ICommander` |
| 函数/方法 | `snake_case` | `get_units_in_range()` `take_damage()` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_TURNS` `MAP_DEFAULT_WIDTH` |
| 私有成员 | `_` 前缀 | `_handlers` `_validate_constants()` |
| 枚举值 | `UPPER_SNAKE_CASE` | `Faction.FRIENDLY` `UnitType.INFANTRY` |
| 变量 | `snake_case` | `unit_count` `current_hp` |

---

## 3. 类型注解

```python
# ✅ 正确 — 所有公开函数必须有类型注解
def get_units_in_range(
    center: Coordinate,
    radius: int,
    faction: Faction | None = None,
) -> list[IUnit]:
    ...

# ✅ 正确 — 使用 Optional 和 Union 的现代语法（Python 3.11+）
def find_target(self, units: list[IUnit]) -> IUnit | None:
    ...

# ❌ 错误 — 缺少类型注解
def get_units_in_range(center, radius, faction=None):
    ...

# ❌ 错误 — 使用旧式 Optional（CI 会拦截）
from typing import Optional
def foo(x: Optional[int]) -> ...
```

---

## 4. Docstring（Google 风格）

```python
def calculate_damage(
    attacker: IUnit,
    defender: IUnit,
    terrain_bonus: int = 0,
) -> int:
    """计算攻击方对防御方造成的实际伤害。

    伤害公式：max(1, attack - defense) × 兵种克制倍率

    Args:
        attacker: 攻击方单位
        defender: 防御方单位
        terrain_bonus: 防御方地形防御加成（默认 0）

    Returns:
        实际伤害值，最小为 1

    Raises:
        ValueError: 若攻击方攻击范围为 0（不可攻击）
    """
    ...
```

---

## 5. Import 规范

```python
# ✅ 正确 — 顺序：标准库 → 第三方 → 项目内部（isort 自动处理）
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Final

import pygame

from src.core.constants import (
    Coordinate,
    Faction,
    GameEventType,
)

# ✅ 正确 — 避免使用 * 导入（测试文件除外）
from src.core import Faction, UnitType

# ❌ 错误 — * 导入（生产代码禁止）
from src.core.constants import *
```

**跨层 import 限制：**

```python
# ✅ #3 业务层 — 只能 import src.core（接口 + 常量 + 事件总线）
from src.core import IUnit, IMap, GameEventType, event_bus

# ✅ #4 UI 层 — 只能 import src.core（接口 + 常量 + 事件总线）
from src.core import IFogOfWar, event_bus

# ❌ 禁止 — 跨层 import 内部实现
from src.battle.units import Infantry     # UI 不能直接 import 业务层
from src.ui.map_widget import MapWidget   # 业务层不能 import UI 层
```

---

## 6. 类结构

```python
class ClassName(ParentClass):
    """类文档字符串（一行简述）。"""

    # ── 类变量 ──────────────────────────────────────────────────
    DEFAULT_VALUE: Final[int] = 42

    # ── __init__ 和特殊方法 ─────────────────────────────────────
    def __init__(self, ...) -> None:
        ...

    # ── 属性 ────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        ...

    # ── 公开方法 ────────────────────────────────────────────────
    def public_method(self) -> None:
        ...

    # ── 私有方法 ────────────────────────────────────────────────
    def _private_helper(self) -> int:
        ...
```

**分组注释**：用 `# ── 分组名 ──` 分隔类内不同功能区域（见上面示例）。

---

## 7. 文件头注释

```python
"""
模块简短描述（一行）。

详细说明（可选，多行）。
"""

# 只在必要时添加 shebang 或 encoding 声明
```

不需要作者、日期等元信息——Git 历史记录这些。

---

## 8. 错误处理

```python
# ✅ 正确 — 明确的异常类型
raise ValueError(f"坐标 ({x}, {y}) 超出地图范围")

# ❌ 错误 — 裸 except 或泛化异常
except:
    pass
```

EventBus 回调中的异常由 EventBus 自动捕获并记录日志，回调内部不需要额外 try/except。

---

## 9. 禁止事项

| 禁止 | 原因 |
|------|------|
| `from X import *`（生产代码） | 命名空间污染 |
| 裸 `except:` | 隐藏 bug |
| `print()` 调试（生产代码） | 使用 `logging` |
| 硬编码魔法数字 | 用 `constants.py` 中的常量 |
| 修改 `src/core/` 下 Phase 0 文件 | 需 PR + Review |
| 跨层 import | 破坏三层隔离 |
| `# type: ignore` 无注释 | 如果必须跳过 mypy，写清楚原因 |

---

## 10. Git 提交信息

```
类型: 简短描述

类型可选：feat / fix / docs / chore / refactor / test

示例：
  feat: 实现步兵兵种类
  fix: 修复地图越界判断
  docs: 更新指令集说明
  chore: 配置 pre-commit hooks
  test: 添加对战伤害计算测试
```

---

> **工具会自动执行本规范中的绝大部分检查。人工只需关注命名、docstring、架构分层。**
