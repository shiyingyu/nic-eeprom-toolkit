# NIC EEPROM Toolkit

[English](README.md)

一组用于读取、分析和修改以太网网卡（NIC）EEPROM 二进制镜像的命令行工具。

本仓库不限定于某一款网卡芯片。后续新增芯片时，将针对各自的 EEPROM 布局增加独立的解析和修改逻辑。**当前版本实现了 Intel 82599 支持。**

> **功能范围：** 本仓库中的工具只处理 EEPROM 镜像文件，不直接访问网卡、不读取物理 EEPROM，也不负责将镜像烧录到设备。

## 功能

### Intel 82599 EEPROM 读取工具

`82599_eeprom_dump.py` 读取原始 EEPROM 二进制镜像，并显示常用配置：

- Port 0 和 Port 1 的 LAN Core 模块指针。
- 两个端口各自的 MAC 地址。
- LED0～LED3 的工作模式、极性和闪烁标志。
- 全局 LED 闪烁周期。
- LAN Core 模块中存在 SDP 配置时，显示 SDP 控制信息。
- EEPROM word `0x2B` 指向的 SFP/PHY 初始化类型表：模块类别 ID 及其初始化数据指针。
- EEPROM word `0x2C` 的 Device Capabilities，以及 `ALLOW_ANY_SFP`（bit 0）状态。
- Intel 82599 软件 EEPROM checksum 状态。

读取工具为只读操作，不会修改输入文件。

### Intel 82599 EEPROM 修改工具

`82599_eeprom_edit.py` 使用可重复输入的 `--set KEY=VALUE` 参数修改指定配置：

- 各端口 MAC 地址。
- LED0～LED3 的工作模式。
- LED 输出极性。
- 每个 LED 的闪烁使能状态。
- 每个端口的全局闪烁周期。
- 全局 SFP 厂商限制开关 `sfp.allow-any`，对应 EEPROM word `0x2C` 的 bit 0（`ALLOW_ANY_SFP`）。

修改器会跟随 EEPROM 中的 LAN Core 模块指针定位端口数据，而不是假定配置位于固定绝对地址。修改时只更新指定字段；修改某个 LED 时会保留同一个 EEPROM word 中另一个 LED 的配置。修改 `sfp.allow-any` 时只修改 Device Capabilities 的 bit 0，其他位保持不变。完成后自动重新计算 82599 软件 checksum。

修改器不会覆盖原始输入文件。默认在旁边生成 `<输入文件名>_modified.bin`。如果目标输出文件已经存在，必须显式指定 `--force` 才会覆盖。

### X520-DA2 预设（Windows）

`82599_x520_apply.bat` 是一个针对 Intel X520-DA2 电路连接方式的 Windows 批处理预设：

| 端口 | EEPROM LED | 原理图信号 | 功能模式 | 极性 |
|---|---:|---|---|---|
| SFP0 | LED0 | `SFP0_LED0_LINK_UP`（AD14） | `link-up` | `active-low` |
| SFP0 | LED2 | `SFP0_LED2_LINK/ACT`（AB14） | `link-activity` | `active-low` |
| SFP1 | LED0 | `SFP1_LED0_LINK_UP`（AD13） | `link-up` | `active-low` |
| SFP1 | LED2 | `SFP1_LED2_LINK/ACT`（AB13） | `link-activity` | `active-low` |

批处理文件还会设置两个端口的 MAC 地址，并默认设置 `sfp.allow-any=on`（Device Capabilities word `0x2C` 的 bit 0）。在 Linux `ixgbe` 驱动中，这会绕过适用光模块的厂商 OUI 限制，但不保证所有第三方模块都能正常工作。**实际使用前，必须将批处理文件中的示例 MAC 地址替换为分配给该网卡的唯一地址。** 如不希望开启此策略，可将批处理文件顶部的 `ALLOW_ANY_SFP` 改为 `off`。

## 环境要求

- Python 3.10 或更高版本。
- 不依赖第三方 Python 包。
- `.bat` 批处理文件适用于 Windows。

## 输入镜像格式

当前 82599 工具要求输入文件满足以下条件：

- 镜像从 EEPROM word 地址 `0x0000` 开始。
- 每个 EEPROM word 为 16 位，按 little-endian（小端）排列。
- 文件内容是 EEPROM 原始镜像本身，不包含额外的文件头或容器格式。

可以使用网卡厂商工具或合适的硬件编程器获取二进制镜像。本仓库不涉及物理硬件的读取和烧录方法。

## 使用方法

### 1. 读取 EEPROM 镜像

读取两个端口：

```bash
python 82599_eeprom_dump.py eeprom.bin
```

只读取 Port 0 或 Port 1：

```bash
python 82599_eeprom_dump.py eeprom.bin --port 0
python 82599_eeprom_dump.py eeprom.bin --port 1
```

查看命令帮助：

```bash
python 82599_eeprom_dump.py --help
```

### 2. 修改 EEPROM 镜像

修改器至少需要一个 `--set` 参数。每个需要修改的字段分别使用一个 `--set`：

```bash
python 82599_eeprom_edit.py eeprom.bin \
  --set port0.mac=02:00:00:00:00:10 \
  --set port1.mac=02:00:00:00:00:11 \
  --set port0.led0.mode=link-up \
  --set port0.led0.polarity=active-low \
  --set port0.led2.mode=link-activity \
  --set port0.led2.polarity=active-low \
  --set port1.led0.mode=link-up \
  --set port1.led0.polarity=active-low \
  --set port1.led2.mode=link-activity \
  --set port1.led2.polarity=active-low \
  -o eeprom_modified.bin
```

不指定 `-o` 时，修改器会在输入文件旁边创建 `<输入文件名>_modified.bin`。如果输出文件已经存在，需要显式添加 `--force` 才会覆盖。即使使用 `--force`，也不会覆盖原始输入文件。

查看所有支持的参数、可选值、定义和示例：

```bash
python 82599_eeprom_edit.py --help
```

### 3. 在 Windows 下执行 X520-DA2 预设

将批处理文件与 `82599_eeprom_edit.py` 放在同一个目录。先修改批处理文件顶部的 `MAC_SFP0` 和 `MAC_SFP1`，然后执行：

```bat
82599_x520_apply.bat X520-DA2.bin
```

也可以指定输出文件路径：

```bat
82599_x520_apply.bat X520-DA2.bin X520-DA2_custom.bin
```

该预设只生成新的二进制镜像，不会直接对物理网卡进行烧录。

## 82599 修改器支持的参数

`N` 表示端口编号（`0` 或 `1`）；`M` 表示 LED 编号（`0`～`3`）。

| 参数 | 可选值 | 说明 |
|---|---|---|
| `portN.mac` | 单播 MAC 地址，例如 `02:00:00:00:00:10` | 设置对应端口的 MAC 地址。不接受全 0、全 `FF` 或组播地址。 |
| `portN.ledM.mode` | 见下方 LED 模式表 | 设置 LED 工作模式。 |
| `portN.ledM.polarity` | `active-low`、`active-high` | 设置极性编码。本工具中，`active-low` 对应 `IVRT=0`，`active-high` 对应 `IVRT=1`。 |
| `portN.ledM.blink` | `on`、`off` | 设置 LED 闪烁位；具体要求受工作模式约束。 |
| `portN.blink-rate` | `200ms`、`83ms` | 设置该端口的全局闪烁周期。 |
| `sfp.allow-any` | `on`、`off` | 设置 EEPROM word `0x2C` 的 `ALLOW_ANY_SFP`（bit 0）。`on` 允许 Linux `ixgbe` 驱动跳过适用光模块的常规厂商 OUI 限制；`off` 则清除此位。只修改 bit 0，保留该 word 的其他位。 |

### SFP 厂商策略与 PHY 初始化表

82599 EEPROM 中有两个用途不同的 SFP 相关字段：

- **Word `0x2B`：PHY 初始化类型表指针。** 它指向一个由模块类型 ID 和初始化数据指针组成的索引表。dump 工具会跟随指针读取该表。表中记录的是模块类别对应的 PHY 初始化序列，不是允许使用的厂商名单，也不是具体 SFP 型号白名单。
- **Word `0x2C`：Device Capabilities。** bit 0 为 `ALLOW_ANY_SFP`。edit 工具通过 `--set sfp.allow-any=on` 或 `--set sfp.allow-any=off` 修改该位。

`ALLOW_ANY_SFP` 的作用需要结合驱动理解：在 Linux `ixgbe` 驱动中，该位会影响适用 SFP 光模块的厂商 OUI 检查；置位后，驱动跳过通常的 OUI 厂商限制。但它**不会关闭所有模块识别和兼容性检查**。驱动仍会读取模块 Identifier、速率/应用合规信息，判断模块类别，并查找相应 PHY 初始化序列。因此，置位不代表任意第三方模块都能工作，也不代表 Intel 官方将其列为经过验证或支持的模块。具体还取决于模块 EEPROM 信息、电气/光学规格、PHY 初始化要求、驱动和系统配置。

Linux 驱动的具体判断可参考 [Linux `ixgbe` PHY 实现](https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/ixgbe/ixgbe_phy.c)；Intel 官方的 [X520 SFP+ 模块支持说明](https://www.intel.com/content/www/us/en/support/articles/000005688/ethernet-products.html)则体现了“驱动可能接受”与“厂商正式测试/支持”之间的区别。

本仓库当前的 X520-DA2 样本镜像中，word `0x2C` 为 `0xFFFF`，因此 `ALLOW_ANY_SFP` 已经置位。文件偏移 `0x56` 处的字节 `6A 0D` 是 word `0x2B` 中指针 `0x0D6A` 的小端表示，不是第三方模块支持标志。

修改示例：

```bash
python 82599_eeprom_edit.py eeprom.bin --set sfp.allow-any=on -o eeprom_any_sfp.bin
```

### LED 工作模式

| 参数值 | 含义 | BLINK 位要求 |
|---|---|---|
| `link-up` | 任意支持速率的链路已建立 | 无特殊要求 |
| `link-10g` | 10 Gb/s 链路 | 无特殊要求 |
| `activity` | MAC 收发活动 | 必须为 on |
| `filtered-activity` | 经过过滤的收发活动 | 必须为 on |
| `link-activity` | 建立链路且空闲时常亮，有数据活动时闪烁 | 必须为 off |
| `link-1g` | 1 Gb/s 链路 | 无特殊要求 |
| `link-100m` | 100 Mb/s 链路 | 无特殊要求 |
| `force-on` | 强制点亮 LED | 无特殊要求 |
| `force-off` | 强制熄灭 LED | 无特殊要求 |

选择要求特定 BLINK 状态的模式时，修改器会自动设置对应的 BLINK 位。如果用户显式指定的 `blink` 值与模式要求冲突，修改器会报错退出，而不是静默覆盖用户输入。

支持的便捷别名包括：`link`、`mac-activity`、`filter-activity`、`link-100`、`on` 和 `off`。帮助信息中列出的是标准参数值。

## 验证情况

82599 工作流程已经使用 Intel X520-DA2 EEPROM 镜像进行过实际验证：先读取镜像，再执行修改；修改后的文件由本项目的 dump 工具重新读取，并使用独立的 [Intel82599eeprom](https://github.com/archaron/Intel82599eeprom) 项目进行交叉检查。

这说明已测试镜像及相关字段的读写流程经过验证，但不代表所有 82599 网卡、EEPROM 镜像变体或硬件版本都必然适用。将镜像写入目标网卡前，应结合目标硬件及其文档再次检查。

## 安全注意事项

1. **保留未经修改的原始 EEPROM 镜像备份。**
2. 修改前确认输入文件是符合预期格式的原始镜像。
3. 使用合法且分配给该网卡的唯一 MAC 地址。文档示例中的 MAC 仅用于演示。
4. 软件 checksum 正确并不能单独证明整个镜像适用于某一具体网卡，也不能保证网卡一定能够正常启动。
5. 修改器会重新计算 82599 软件 checksum word，但不会烧录硬件、验证物理 EEPROM 写入，也不会验证所有硬件相关字段或签名。
6. 物理 EEPROM 操作应使用合适的厂商工具或硬件编程器。在修改生产设备的 EEPROM 前，应先明确恢复方法。

## 当前仓库结构

```text
nic-eeprom-toolkit/
├── README.md
├── README_zh-CN.md
├── 82599_eeprom_dump.py
├── 82599_eeprom_edit.py
└── 82599_x520_apply.bat
```

随着后续支持更多控制器，应将不同芯片的 EEPROM 布局和专用解析逻辑清晰分离，避免与 82599 实现混在一起。

## 后续计划

- 增加对其他以太网网卡及控制器系列的支持。
- 在适当时机抽取通用二进制读写辅助函数，并将芯片专用 EEPROM 布局和字段定义独立管理。
- 为已支持设备增加自动化测试和经过脱敏的 EEPROM 样本镜像。
- 在原理图连接方式和预期 EEPROM 配置明确的前提下，增加更多板卡专用预设。

## 许可证

本项目采用 **MIT License（MIT 许可证）**，完整许可条款请参见 [LICENSE](LICENSE)。

MIT 许可证允许任何人使用、复制、修改、合并、发布、分发、再许可和销售本项目软件及其副本，也允许将其用于商业用途。使用和分发时，须在软件副本或其重要部分中保留原版权声明和许可声明。软件按“现状”提供，不附带任何明示或默示保证；具体权利、条件及免责声明以 `LICENSE` 文件中的英文原文为准。