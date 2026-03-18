# click

这是一个围绕 `HID Remapper` 配置生成和调参的小工具仓库，不是传统意义上的独立应用项目。

这个仓库主要用于：

- 从 HID Remapper 设备录制监控数据
- 根据 CSV 自动微调每一发的压枪参数
- 生成单武器或多武器可导入的 JSON 配置
- 用图形界面可视化和编辑多武器参数

## 上游参考

- 固件 / 上游项目：
  [jfedor2/hid-remapper](https://github.com/jfedor2/hid-remapper)
- 在线配置与调试工具：
  [remapper.org/config](https://www.remapper.org/config/)

本仓库生成的 JSON，目标就是导入上面的 HID Remapper 配置工具。

## 主要流程

1. 用 `rec_lr.cmd` 录制 HID monitor 数据到 CSV。
2. 用 `gen_json.cmd` 生成或回调单武器配置。
3. 用 `wk.cmd` 生成多武器配置。
4. 把生成出的 JSON 导入 HID Remapper 配置页面。

## 顶层脚本

- `rec_lr.cmd`
  录制 monitor 输出到 `data/captures/*.csv`
- `gen_json.cmd`
  生成单武器 JSON，支持可选自动 retune
- `go.cmd`
  顺序执行“录制 -> 生成”
- `wk.cmd`
  生成键盘切枪的多武器配置
- `trajectory_lab.cmd`
  用 `uv` 临时拉起 GUI 依赖，启动图形化轨迹工作台

## 图形化轨迹工作台

仓库里已经包含一个第一版桌面调参工具，主要面向多武器参数文件。

当前支持：

- 打开 `data/params/*.json`
- 切换武器
- 编辑 30 发 `x_steps / y_steps`
- 查看每发步进图
- 查看累计轨迹图
- 直接拖动累计轨迹点来修改某一发
- 记录基准轨迹并和当前轨迹做虚线对比
- 撤销 / 重做
- 保存参数
- 调用 `scripts/build_multi_weapon_config.py` 导出 HID Remapper JSON

启动方式：

```bat
trajectory_lab.cmd
```

或者直接运行：

```bat
uv run --with PySide6 --with pyqtgraph python -m app.main
```

当前范围：

- 支持多武器参数格式：`global + weapons[]`
- 还不支持单武器 `ak_tune_params` 格式的完整 GUI 编辑

详细中文使用说明见：

- `USAGE.md`

## Python 脚本

- `scripts/record_monitor_csv.py`
  通过 `hidapi` 读取 HID monitor 报告
- `scripts/retune_from_csv.py`
  从录制出来的 CSV 自动生成偏移量
- `scripts/apply_ak_tune.py`
  把单武器调参结果写回基础 JSON
- `scripts/build_multi_weapon_config.py`
  把多武器参数编译成 HID Remapper expressions
- `scripts/gen_extra_weapon_configs.py`
  生成额外的武器配置变体

## 目录结构

- `app/`
  图形化轨迹工作台代码
- `data/configs/`
  基础模板和生成后的导入 JSON
- `data/params/`
  武器参数、调参表
- `data/captures/`
  录制得到的 monitor CSV
- `scripts/`
  配置生成、回调、录制相关脚本
- `Sorin/`
  旧版宏/配置参考素材

## 说明

- 当前生成的配置目标格式是 HID Remapper `version 18` JSON
- 浏览器配置工具可用于监控、表达式调试、导入导出、刷写固件等
- 录制链路需要真实 HID Remapper 硬件
