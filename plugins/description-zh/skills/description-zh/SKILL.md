---
name: description-zh
description: 查看本机插件和技能介绍的自动汉化状态，立即检查新增项，暂停、继续或恢复原文。
---

在 Windows 上用 Description ZH 安装的 Python 环境运行本插件的 `scripts/localize.py`。
从本技能所在目录向上两级即可找到插件根目录。Python 位于实际 Codex 用户目录下的
`description-zh/venv/Scripts/python.exe`。优先取 `CODEX_HOME`，默认用用户目录下的 `.codex`。
如果运行环境缺失，请从源码安装目录运行 `enable.ps1`。

| 用户希望做什么 | 脚本子命令 |
|---|---|
| 看状态、排查未翻译项 | `status` |
| 先预览可编辑的介绍 | `preview` |
| 立即检查已选范围 | `scan` |
| 查看可选和已选市场 | `markets` |
| 将后续检查范围设为指定市场 | `markets --market 名称`，重复参数可选多项 |
| 在后续检查中加入指定项目 | `projects --project "项目绝对路径"` |
| 暂停、继续、停止后台 | `pause`、`resume`、`stop` |
| 暂停并恢复原文 | `restore` |

恢复冲突时报告受影响的路径和备份状态。列表刚更新时，可以重新打开插件页或聊天。新译文会使用用户配置的模型服务，已缓存的译文和原文备份保存在本地。
