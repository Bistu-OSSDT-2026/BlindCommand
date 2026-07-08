"""
BlindCommand 抽象接口契约 — 层间隔离的唯一合约
================================================
本文件定义所有跨层调用的抽象接口。
- #2 负责实现这些接口
- #3 只通过接口调用底层能力
- #4 只通过接口查询可见性

修改本文件必须 PR + 至少 2 人 Review，合并后全员 git pull。

版本：v1.0
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.core.constants import (
    CommandType,
    Coordinate,
    Faction,
    GameResult,
    TerrainType,
    UnitType,
)

# ============================================================================
# 第一部分：单位接口（#2 实现基类，#3 通过继承实现具体兵种）
# ============================================================================


class IUnit(ABC):
    """单位抽象接口。

    #2 在 unit_base.py 中实现此接口的基础逻辑，
    #3 在 battle/units.py 中继承并重写 attack_target() 等虚方法。
    """

    # ── 只读属性 ──────────────────────────────────────────────────────

    @property
    @abstractmethod
    def unit_id(self) -> str:
        """全局唯一标识，如 'friendly_infantry_01'。"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """人类可读名称，如 '第一步兵连'。"""
        ...

    @property
    @abstractmethod
    def faction(self) -> Faction:
        """所属阵营。"""
        ...

    @property
    @abstractmethod
    def unit_type(self) -> UnitType:
        """兵种类型。"""
        ...

    @property
    @abstractmethod
    def position(self) -> Coordinate:
        """当前坐标。"""
        ...

    @property
    @abstractmethod
    def max_hp(self) -> int:
        """最大血量。"""
        ...

    @property
    @abstractmethod
    def current_hp(self) -> int:
        """当前血量。"""
        ...

    @property
    @abstractmethod
    def attack(self) -> int:
        """攻击力。"""
        ...

    @property
    @abstractmethod
    def defense(self) -> int:
        """防御力（含地形加成后的最终值）。"""
        ...

    @property
    @abstractmethod
    def speed(self) -> int:
        """每回合可移动格数。"""
        ...

    @property
    @abstractmethod
    def attack_range(self) -> int:
        """攻击范围（格数），0 表示不可攻击。"""
        ...

    @property
    @abstractmethod
    def vision_range(self) -> int:
        """视野范围（格数），0 表示无视野。"""
        ...

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """是否存活。"""
        ...

    @property
    @abstractmethod
    def is_hq(self) -> bool:
        """是否为指挥所单位。"""
        ...

    # ── 操作方法 ──────────────────────────────────────────────────────

    @abstractmethod
    def take_damage(self, amount: int, source: "IUnit") -> int:
        """受到伤害。

        Args:
            amount: 最终伤害值（#3 已计算防御/克制/地形后的值）
            source: 伤害来源单位

        Returns:
            实际扣血量 = min(amount, 扣血前 current_hp)
        """
        ...

    @abstractmethod
    def move_to(self, target: Coordinate) -> bool:
        """移动到目标坐标。

        Returns:
            True 如果移动成功（路径存在且剩余移动力足够）
        """
        ...

    @abstractmethod
    def attack_target(self, target: "IUnit") -> int:
        """攻击目标单位。

        此方法为虚方法，子类（#3）可重写以实现特殊攻击逻辑（如炮兵远程先手）。

        Args:
            target: 被攻击的单位

        Returns:
            实际造成的伤害值
        """
        ...

    @abstractmethod
    def get_state_report(self) -> str:
        """生成单位状态报告（用于战报）。"""
        ...

    @abstractmethod
    def can_attack(self, target: "IUnit") -> bool:
        """判断是否可以攻击目标（距离在攻击范围内 + 目标存活 + 阵营敌对）。"""
        ...


# ============================================================================
# 第二部分：地图接口（#2 实现）
# ============================================================================


class IMap(ABC):
    """地图管理接口。"""

    @property
    @abstractmethod
    def width(self) -> int:
        """地图宽度（列数）。"""
        ...

    @property
    @abstractmethod
    def height(self) -> int:
        """地图高度（行数）。"""
        ...

    @abstractmethod
    def get_terrain(self, coord: Coordinate) -> TerrainType:
        """获取指定坐标的地形类型。"""
        ...

    @abstractmethod
    def is_passable(self, coord: Coordinate) -> bool:
        """坐标是否可通行。"""
        ...

    @abstractmethod
    def is_within_bounds(self, coord: Coordinate) -> bool:
        """坐标是否在地图范围内。"""
        ...

    @abstractmethod
    def get_move_cost(self, coord: Coordinate) -> int:
        """获取通过该格子的移动消耗。不可通行返回 -1。"""
        ...

    @abstractmethod
    def get_defense_bonus(self, coord: Coordinate) -> int:
        """获取该格子的地形防御加成。"""
        ...

    @abstractmethod
    def get_units_at(self, coord: Coordinate) -> list[IUnit]:
        """获取该坐标上的所有单位。"""
        ...

    @abstractmethod
    def place_unit(self, unit: IUnit, coord: Coordinate) -> bool:
        """将单位放置到地图上。

        Returns:
            True 如果放置成功（坐标合法且未被敌对单位占据）
        """
        ...

    @abstractmethod
    def remove_unit(self, unit: IUnit) -> None:
        """从地图上移除单位。"""
        ...

    @abstractmethod
    def move_unit(self, unit: IUnit, from_coord: Coordinate, to_coord: Coordinate) -> bool:
        """移动单位（更新地图格子占用状态）。

        Returns:
            True 如果移动合法
        """
        ...

    @abstractmethod
    def get_faction_hq_location(self, faction: Faction) -> Optional[Coordinate]:
        """获取指定阵营指挥所的坐标。"""
        ...

    @abstractmethod
    def find_path(
        self, start: Coordinate, end: Coordinate, max_steps: int,
        faction: Optional[Faction] = None,
    ) -> list[Coordinate]:
        """A* 寻路。

        Args:
            start: 起点
            end: 终点
            max_steps: 最大步数（受单位 speed 限制）
            faction: 可选，移动单位所属阵营（用于过滤敌军占据格，防止穿过敌方单位）

        Returns:
            路径坐标列表（含起点和终点），若不可达返回空列表
        """
        ...

    @abstractmethod
    def get_neighbors(self, coord: Coordinate) -> list[Coordinate]:
        """获取八邻域坐标（排除越界和不可通行格）。"""
        ...


# ============================================================================
# 第三部分：范围检索接口（#2 实现，#3 战斗系统调用）
# ============================================================================


class IRangeQuery(ABC):
    """范围检索接口——替代原始方案中的"八邻域检索"。"""

    @abstractmethod
    def get_units_in_range(
        self,
        center: Coordinate,
        radius: int,
        faction: Optional[Faction] = None,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[IUnit]:
        """以 center 为中心，radius 为半径，检索范围内的单位。

        Args:
            center: 检索中心坐标
            radius: 检索半径（切比雪夫距离），1 = 八邻域
            faction: 若指定，只返回该阵营的单位；None 返回全部
            exclude_ids: 排除的单位 ID 集合

        Returns:
            范围内的单位列表（按距离由近到远排序）
        """
        ...

    @abstractmethod
    def find_nearest_enemy(self, unit: IUnit) -> Optional[IUnit]:
        """找到某单位视野范围内最近的敌人。"""
        ...

    @abstractmethod
    def has_enemy_in_range(self, unit: IUnit, radius: int) -> bool:
        """某单位指定范围内是否有敌人。"""
        ...


# ============================================================================
# 第四部分：迷雾/视野接口（#2 实现，#4 UI 调用）
# ============================================================================


class IFogOfWar(ABC):
    """迷雾与视野管理接口。

    关键设计：迷雾计算逻辑归属 #2（底层数据层），
    #4（UI 层）只调用查询接口获取可见性，然后决定"怎么显示"。
    """

    @abstractmethod
    def is_visible_to_faction(self, coord: Coordinate, faction: Faction) -> bool:
        """指定坐标对指定阵营是否可见。

        若 faction 的任一单位视野覆盖该坐标，则返回 True。
        """
        ...

    @abstractmethod
    def is_unit_visible(self, unit: IUnit, to_faction: Faction) -> bool:
        """指定单位对指定阵营是否可见。"""
        ...

    @abstractmethod
    def get_visible_area(self, faction: Faction) -> set[Coordinate]:
        """获取指定阵营当前可见的所有坐标集合。"""
        ...

    @abstractmethod
    def get_approximate_position(
        self, unit: IUnit
    ) -> Coordinate:
        """获取单位向玩家汇报的"带误差的大致坐标"。

        仅对 FRIENDLY 阵营单位有效。误差半径由 FOG_POSITION_ERROR_RADIUS 控制。
        """
        ...

    @abstractmethod
    def should_report_position(self, unit: IUnit, current_turn: int) -> bool:
        """判断该友军单位本回合是否需要汇报位置。"""
        ...

    @abstractmethod
    def init_report_schedule(self, unit: IUnit, current_turn: int) -> None:
        """初始化单位的汇报调度（单位创建/游戏开始时调用）。

        仅对 FRIENDLY 阵营有效。安排首次汇报回合。
        """
        ...

    @abstractmethod
    def on_position_reported(self, unit: IUnit, current_turn: int) -> None:
        """汇报完成后调用，安排下次汇报回合。

        由 GameLoop 在实际 emit POSITION_REPORT 后调用。
        """
        ...

    @abstractmethod
    def remove_report_schedule(self, unit_id: str) -> None:
        """移除单位的汇报调度条目（阵亡/注销时调用，幂等）。"""
        ...


# ============================================================================
# 第五部分：游戏主循环接口（#2 实现）
# ============================================================================


class IGameLoop(ABC):
    """游戏主循环接口。"""

    @abstractmethod
    def start(self) -> None:
        """启动游戏主循环。"""
        ...

    @abstractmethod
    def pause(self) -> None:
        """暂停游戏。"""
        ...

    @abstractmethod
    def resume(self) -> None:
        """恢复游戏。"""
        ...

    @abstractmethod
    def get_current_turn(self) -> int:
        """获取当前回合数。"""
        ...

    @abstractmethod
    def get_all_units(self, faction: Optional[Faction] = None) -> list[IUnit]:
        """获取所有存活单位。"""
        ...

    @abstractmethod
    def get_game_result(self) -> Optional[GameResult]:
        """获取游戏结果，未结束时返回 None。"""
        ...

    @abstractmethod
    def check_victory_conditions(self) -> Optional[GameResult]:
        """检查胜利/失败条件。"""
        ...


# ============================================================================
# 第六部分：指令系统接口（#3 实现）
# ============================================================================


class ICommand(ABC):
    """单条指令的抽象。"""

    @property
    @abstractmethod
    def command_type(self) -> CommandType:
        """指令类型。"""
        ...

    @property
    @abstractmethod
    def target_unit_id(self) -> str:
        """目标单位 ID。"""
        ...

    @abstractmethod
    def execute(self, unit: IUnit, game_state: "IGameState") -> bool:
        """执行指令。

        Args:
            unit: 执行指令的单位
            game_state: 当前游戏状态（只读查询）

        Returns:
            True 如果指令执行完成（不再需要继续），False 如果还需要下回合继续
        """
        ...

    @abstractmethod
    def get_human_description(self) -> str:
        """返回人类可读的指令描述（用于战报）。"""
        ...


class ICommander(ABC):
    """指令管理与传达系统接口（#3 实现）。"""

    @abstractmethod
    def issue_command(
        self, unit_id: str, command_type: CommandType, params: dict[str, object]
    ) -> bool:
        """向指定单位下达指令。指令进入传达队列，经历通信延迟后到达。

        Args:
            unit_id: 目标单位 ID
            command_type: 指令类型
            params: 指令参数（如 {"x": 10, "y": 5}）

        Returns:
            True 如果指令有效（单位存在且存活）
        """
        ...

    @abstractmethod
    def process_command_queue(self, current_turn: int) -> list[ICommand]:
        """处理传达队列，返回本回合到期的指令列表。

        由主循环每回合调用。
        """
        ...

    @abstractmethod
    def get_pending_commands(self, unit_id: str) -> list[ICommand]:
        """获取某单位待执行的指令队列。"""
        ...

    @abstractmethod
    def cancel_all_commands(self, unit_id: str) -> None:
        """取消某单位的所有未执行指令（阵亡时调用）。"""
        ...


# ============================================================================
# 第七部分：游戏状态只读接口（供指令执行时查询上下文）
# ============================================================================


class IGameState(ABC):
    """游戏状态只读查询接口。#3 的指令执行时通过此接口获取上下文。"""

    @abstractmethod
    def get_unit_by_id(self, unit_id: str) -> Optional[IUnit]:
        """按 ID 查找单位。"""
        ...

    @abstractmethod
    def get_map(self) -> IMap:
        """获取地图对象。"""
        ...

    @abstractmethod
    def get_range_query(self) -> IRangeQuery:
        """获取范围检索工具。"""
        ...

    @abstractmethod
    def get_fog(self) -> IFogOfWar:
        """获取迷雾/视野管理器（供 #4 UI 查询可见性）。"""
        ...

    @abstractmethod
    def get_current_turn(self) -> int:
        """获取当前回合数。"""
        ...


# ============================================================================
# 第八部分：事件总线接口（#2 实现）
# ============================================================================

# EventBus 是具体类而非接口——它不需要多态，只需要可靠。
# 接口契约：事件类型与载荷类型的映射在 constants.py 的 EVENT_PAYLOAD_MAP 中定义。
# EventBus 的实现在 event_bus.py 中。

EventHandler = Callable[..., None]
"""事件处理回调的类型别名。回调参数由具体事件的 payload dataclass 决定。"""
