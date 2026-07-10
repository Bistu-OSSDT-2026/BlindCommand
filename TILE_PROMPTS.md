# 地形瓦片 & 兵种图标生成方案

> **用途**: 1 张基底纹理 + 14 张地形符号 + 12 张兵种/状态图标  
> **风格**: 一战末期总参谋部地图桌 — 泛黄亚麻纸上手绘铅笔符号  
> **策略**: 基底 1 张覆盖全图，地形/兵种全部透明 PNG 叠加，零纸色匹配问题  
> **工具**: Kling (kling-image-o1) + PS 去底

---

## 核心设计

### 架构

```
层 0: 基底纹理（1 张 2048×2048 泛黄亚麻纸，平铺覆盖整个地图）
层 1: 地形符号（14 张透明 PNG，逐格叠加在基底上）
层 2: 兵种图标（12 张透明 PNG）
层 3: 玩家标记（4 张，后续）
层 4: 迷雾遮罩（1 张，后续）
```

所有符号共享同一张基底纸面——不存在纸色匹配问题。每个地形符号是透明背景上的铅笔标记，覆盖在纸面上就像直接画在地图上。

### 为什么单符号瓦片

森林瓦片 = 透明背景上一棵铅笔树。代码重复贴到连续格 → 一片树林。完全相同的符号重复出现，无拼接问题。

每种地形 2-3 张微变体，随机轮换消除机械重复感。

### 风格一致性

所有地形符号用 `text_to_image` 生成时统一铅笔风格描述。基底单独生成，作为全图的纸面基础。

---

## 生成要求

### 环境

```
CLI:     kling（@klingai/cli-cn，已登录）
模型:    kling-image-o1
命令:    text_to_image（全部素材——基底、地形符号、兵种图标）
          基底不参考任何图
          地形符号和兵种图标均为纯白背景 + PS 后期去底变透明
```

### 通用参数

```
--model kling-image-o1
--aspect_ratio 1:1
--img_resolution 2k          # 仅基底用 2k（2048×2048）
--img_resolution 1k          # 其余用 1k（1024×1024）
--poll 90
```

### 命令模板

```
# 基底
kling text_to_image --model kling-image-o1 --aspect_ratio 1:1 --img_resolution 2k --poll 90 "<提示词>"

# 地形符号
kling text_to_image --model kling-image-o1 --aspect_ratio 1:1 --img_resolution 1k --poll 90 "<提示词>"

# 兵种图标
kling text_to_image --model kling-image-o1 --aspect_ratio 1:1 --img_resolution 1k --poll 90 "<提示词>"
```

### 生成顺序

```
1. base             基底纹理（2048×2048，不参考任何图）
2. plain            空白（纯白背景，不参考任何图）
3. forest_1/2/3     3 棵树
4. mountain_1/2/3   3 座山
5. river_h/v/d1/d2  4 向水纹
6. hq               HQ 建筑群
7. bridge_h/v       横桥/竖桥
8. 12 张兵种图标

全部 text_to_image，同套铅笔风格描述锁定一致性。
```

### 后期去底（所有符号素材）

```
每张生成后：
1. PS/GIMP 打开
2. 魔棒工具点击白色背景（容差 ~20）
3. 删除选中区域 → 透明背景
4. 橡皮擦清理边缘残留白边
5. 导出 PNG（RGBA，保留透明通道）
```

### 每张检查

| 检查项 | 通过标准 |
|------|------|
| 纯白背景 | 无纸纹理残留，方便去底 |
| 单符号 | 中央只有一个地形符号 |
| 符号居中 | 四周留白均匀 |
| 变体差异 | 同种变体之间明显不同但风格一致 |
| 无文字 | 不能出现 AI 文字/字母 |

---

## 瓦片使用方式

```
代码渲染：
  for each grid cell:
    terrain_code = map[row][col]
    variant = random_pick(terrain_variants[terrain_code])
    blit(variant, cell_rect)

地形变化 = 不同格贴不同瓦片
同种地形 = 同一批瓦片重复贴
完全相同的瓦片贴在一起 → 零边界问题
```

---

# 基底纹理

> 2048×2048。整个地图的纸面基础，平铺覆盖。只生成 1 张。

### `base.png`

```
Top-down macro photograph of a large section of antique linen military map parchment from a World War I general staff war table. The parchment is aged yellowed cream with a warm ivory undertone. Visible coarse linen fabric weave texture throughout. Soft warm lamplight from a brass desk lamp. The paper is entirely blank — no symbols, no marks, no text. Just the natural fabric weave, faint brown age spots scattered across the surface, and the warm cream tone of the aged paper. This is the blank canvas of the war map, waiting for terrain symbols to be placed upon it. No grid lines, no borders. Muted desaturated: cream, sepia. No digital art feel.
```

---

# 地形符号

> 全部 1024×1024，纯白背景 + PS 去底变透明，覆盖在基底之上。

## 地形符号共享前缀

```
A single hand-drawn terrain symbol in rough pencil sketch style, isolated on pure solid white background for easy background removal. The symbol is:
```

## 地形符号共享后缀

```
Hand-drawn sketch style with visible pencil strokes and cross-hatch shading — rough, textured, like a field sketch in a military notebook. Lines are visible and have character, not faint whispers. Slight wobbles and uneven pressure throughout. Authentic 1918 staff cartography sketch style. The symbol is centered, surrounded by blank white. Graphite pencil sketch aesthetic. No paper texture, no grid lines, no text labels. No digital art feel, no perfect vector lines. Isolated on pure solid white background.
```

---

## 十四张地形符号

### 1. 平原 — `plain.png`

> 留空。纯白背景即可——代表"不叠加任何符号"。也无需 Kling 生成。

> 直接创建一张 1024×1024 纯白 PNG。PS 去底后是全透明——贴到基底上不留痕迹。

---

### 2-4. 森林 — 3 棵不同的树

#### `forest_1.png`
```
[PREFIX] a single hand-drawn tree in rough pencil sketch style — a rounded canopy built from small irregular scribbled circles, above a short trunk. Cross-hatch shading on one side. The strokes are visible and sketchy. The tree is centered and occupies about 40-50 percent of the image. Graphite pencil, field-sketch quality. Only this one tree.
[SUFFIX]
```

#### `forest_2.png`
```
[PREFIX] a single hand-drawn tree in rough pencil sketch style — same type of rounded canopy as forest_1, but slightly taller and the shading is on the opposite side. Same sketchy graphite pencil strokes, same size, same centered position. Subtle variation only — a sibling of the same tree, not a different species.
[SUFFIX]
```

#### `forest_3.png`
```
[PREFIX] a single hand-drawn tree in rough pencil sketch style — same type of rounded canopy, but slightly wider and bushier with a barely bent trunk. Same sketchy graphite pencil strokes, same size, same centered position. Subtle variation only — a sibling of the same tree.
[SUFFIX]
```

---

### 5-7. 山地 — 3 座不同的山

#### `mountain_1.png`
```
[PREFIX] a single hand-drawn mountain peak in rough pencil sketch style — a triangular shape with a pointed summit, cross-hatch shading on one face. Visible sketchy pencil lines. The mountain is centered and occupies about 40-50 percent of the image. Graphite pencil, field-sketch quality. Only this one mountain.
[SUFFIX]
```

#### `mountain_2.png`
```
[PREFIX] a single hand-drawn mountain peak in rough pencil sketch style — same triangular peak as mountain_1, but slightly broader with a gentler slope. Same cross-hatch shading, same size, same centered position. Subtle variation only — a sibling of the same mountain.
[SUFFIX]
```

#### `mountain_3.png`
```
[PREFIX] a single hand-drawn mountain peak in rough pencil sketch style — same triangular peak, but slightly sharper with a steeper face. Same cross-hatch shading, same size, same centered position. Subtle variation only — a sibling of the same mountain.
[SUFFIX]
```

---

### 8-11. 河流 — 4 种流向

> 素描风格水纹填满整个画面。线性的，上下贯通。

#### `river_h.png` — 横流
```
[PREFIX] a full-field water texture in rough pencil sketch style — visible horizontal flowing strokes from left to right, filling the entire image edge to edge. The strokes are sketchy blue pencil lines with character, not faint. Prussian blue colored pencil, rough textured shading throughout. No blank areas — the image is entirely filled with sketchy water strokes. Field-sketch quality.
[SUFFIX]
```

#### `river_v.png` — 纵流
```
[PREFIX] a full-field water texture in rough pencil sketch style — visible vertical flowing strokes from top to bottom, filling the entire image edge to edge. Sketchy blue pencil lines with character. Prussian blue colored pencil, rough textured shading throughout. No blank areas. Field-sketch quality.
[SUFFIX]
```

#### `river_d1.png` — 左上→右下
```
[PREFIX] a full-field water texture in rough pencil sketch style — visible diagonal flowing strokes from top-left to bottom-right, filling the entire image. Sketchy blue pencil lines with character. Prussian blue colored pencil, rough textured shading. No blank areas. Field-sketch quality.
[SUFFIX]
```

#### `river_d2.png` — 右上→左下
```
[PREFIX] a full-field water texture in rough pencil sketch style — visible diagonal flowing strokes from top-right to bottom-left, filling the entire image. Sketchy blue pencil lines with character. Prussian blue colored pencil, rough textured shading. No blank areas. Field-sketch quality.
[SUFFIX]
```

---

### 12. 指挥所 — `hq.png`

```
[PREFIX] a headquarters compound in rough pencil sketch style — a main building with surrounding outbuildings and a flagpole. Drawn in both Prussian blue and brick red colored pencil simultaneously, the two colors slightly offset. Cross-hatch shading on the building faces. Tiny handwritten HQ nearby. The compound is centered, occupies about 40 percent. Sketchy field-drawing quality. Only this one HQ compound.
[SUFFIX]
```

---

### 13-14. 桥梁 — 2 种方向

#### `bridge_h.png` — 横桥（跨竖河）

```
[PREFIX] the entire image is filled with sketchy vertical-flowing blue pencil water texture from top to bottom — visible Prussian blue strokes with character. Across the center, two parallel horizontal graphite pencil lines span from left edge to right edge — a bridge crossing the water. Rough sketch quality, engineer's precision with a human wobble. Small tick marks at ends. Water fills the whole image.
[SUFFIX]
```

#### `bridge_v.png` — 竖桥（跨横河）

```
[PREFIX] the entire image is filled with sketchy horizontal-flowing blue pencil water texture from left to right — visible Prussian blue strokes with character. Across the center, two parallel vertical graphite pencil lines span from top edge to bottom edge — a bridge crossing the water. Rough sketch quality, engineer's precision with a human wobble. Small tick marks at ends. Water fills the whole image.
[SUFFIX]
```

---

# 兵种图标

> 透明背景铅笔符号。生成 1024×1024，纯白背景，PS 去底。

## 兵种图标共享前缀

```
A single hand-drawn military unit symbol, isolated on pure solid white background for easy background removal. The symbol is:
```

## 兵种图标共享后缀

```
Hand-drawn sketch style with visible pencil strokes — rough, like a field sketch in a military notebook. Slight line wobbles and uneven pressure. Authentic 1918 staff cartography sketch style. No paper texture, no grid lines, no text labels. Muted desaturated pencil colors. No digital art feel, no perfect vector lines. Isolated on pure solid white background.
```

## 后期去底

```
1. PS/GIMP 打开 → 魔棒工具点击白色背景（容差 ~20）
2. 删除选中区域 → 橡皮擦清理边缘白边
3. 导出 PNG（RGBA，保留透明通道）
```

---

## 12 张兵种/状态图标

### 友军步兵 — `infantry_blue.png`
```
[PREFIX] a small rectangle with a bold X-shaped diagonal cross inside, drawn in dull Prussian blue colored pencil — the muted dusty blue of a well-worn military pencil. The strokes are slightly rough, blue pigment unevenly deposited. A faint erased ghost of the same symbol slightly offset nearby.
[SUFFIX]
```

### 敌军步兵 — `infantry_red.png`
```
[PREFIX] a small rectangle with a bold X-shaped diagonal cross inside, drawn in dull brick red colored pencil — the muted dusty red of an old colored pencil. The strokes are slightly rough, red pigment unevenly deposited. A faint erased ghost of the same symbol slightly offset nearby.
[SUFFIX]
```

### 友军骑兵 — `cavalry_blue.png`
```
[PREFIX] a small rectangle with a single decisive diagonal slash line from top-right to bottom-left inside, drawn in dull Prussian blue colored pencil. The diagonal was drawn with one confident stroke, slightly heavier at the start. Faint eraser smudges near the edges.
[SUFFIX]
```

### 敌军骑兵 — `cavalry_red.png`
```
[PREFIX] a small rectangle with a single decisive diagonal slash line from top-right to bottom-left inside, drawn in dull brick red colored pencil. The diagonal was drawn with one confident stroke, slightly heavier at the start. Faint eraser smudges near the edges.
[SUFFIX]
```

### 友军炮兵 — `artillery_blue.png`
```
[PREFIX] a small rectangle with a filled circular dot at its center, drawn in dull Prussian blue colored pencil. The center dot is slightly irregular, hand-filled with small circular scribbling motions. Faint eraser residue smeared nearby.
[SUFFIX]
```

### 敌军炮兵 — `artillery_red.png`
```
[PREFIX] a small rectangle with a filled circular dot at its center, drawn in dull brick red colored pencil. The center dot is slightly irregular, hand-filled with small circular scribbling motions. Faint eraser residue smeared nearby.
[SUFFIX]
```

### 友军侦察兵 — `scout_blue.png`
```
[PREFIX] a small diamond shape, a square rotated 45 degrees, drawn in dull Prussian blue colored pencil. The four sides show slight asymmetry from being drawn freehand. Faint erased ghost marks of a previous diamond slightly offset nearby.
[SUFFIX]
```

### 敌军侦察兵 — `scout_red.png`
```
[PREFIX] a small diamond shape, a square rotated 45 degrees, drawn in dull brick red colored pencil. The four sides show slight asymmetry from being drawn freehand. Faint erased ghost marks of a previous diamond slightly offset nearby.
[SUFFIX]
```

### 友军 HQ — `hq_unit_blue.png`
```
[PREFIX] a small rectangular flag flying from a short vertical pole, drawn in dull Prussian blue colored pencil. The flag rectangle has slightly wavy edges. A tiny dot of darker blue at the pole base. Eraser smudges nearby. This is a unit marker symbol, smaller and simpler than a terrain HQ tile.
[SUFFIX]
```

### 敌军 HQ — `hq_unit_red.png`
```
[PREFIX] a small rectangular flag flying from a short vertical pole, drawn in dull brick red colored pencil. The flag rectangle has slightly wavy edges. A tiny dot of darker red at the pole base. Eraser smudges nearby. This is a unit marker symbol, smaller and simpler than a terrain HQ tile.
[SUFFIX]
```

### 阵亡标记 — `dead_marker.png`
```
[PREFIX] a bold cancellation cross drawn heavily in dark brick red colored pencil — two thick diagonal lines forming a large X, drawn with aggressive pressure that left deep grooves in the pencil pigment. Smudged red and graphite halo around the cross from a frustrated eraser. The visual message: this unit has been struck from the order of battle.
[SUFFIX]
```

### 选中高亮 — `selected_highlight.png`
```
[PREFIX] a thin slightly uneven oval loop drawn in soft grey graphite pencil around an empty central area — the kind of casual circling a commander makes during a briefing. The line is light and tentative, drawn freehand with natural wobble and varying pressure. Barely visible, a whisper of graphite. Not a perfect ellipse — a human gesture captured in pencil.
[SUFFIX]
```

---

# 整体架构

```
地图渲染 = 三层叠加

层 0: 基底纹理（1 张 2048×2048） ← 泛黄亚麻纸，平铺覆盖整个地图
层 1: 地形符号（6 种 × 变体）    ← 逐格 stamp，代码随机选变体
层 2: 玩家标记                   ← 数字 + 兵种图标，从托盘拖出，可再拖/右键删除
层 3: 汇报圈                     ← report_circle.png，短暂出现后消失，在最上方

网格线：隐藏（代码不绘制）。
单位真实位置永不渲染。
```

---

# 文件对照

| 文件 | 尺寸 | 数量 | 说明 |
|------|------|:--:|------|
| `base.png` | 2048 | 1 | 泛黄亚麻纸基底，平铺 |
| `plain.png` | 1024 | 1 | 全透明（纯白图去底） |
| `forest_1/2/3.png` | 1024 | 3 | 三棵铅笔树 |
| `mountain_1/2/3.png` | 1024 | 3 | 三座铅笔山 |
| `river_h/v/d1/d2.png` | 1024 | 4 | 四向水纹 |
| `hq.png` | 1024 | 1 | HQ 建筑群 |
| `bridge_h/v.png` | 1024 | 2 | 横桥/竖桥 |
| 12× 兵种/状态图标 | 1024 | 12 | 透明背景 |
| **总计** | | **27** | Kling 调用 26 次（平原无需生成） |
