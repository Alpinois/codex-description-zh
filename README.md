# Description ZH

在 Windows 的 Codex 桌面版里，用简单的中文看懂插件和技能（Skill）是做什么的。市场卡片、插件详情，以及聊天输入框里可编辑的技能点名简介都可以汉化。名称、命令和技能正文保留原样。

启动后台检查后，新装插件、新加技能和已选市场中的新介绍会自动处理。译文会缓存，原文可以恢复。

## 安装

需要 Windows 10 或 11、Python 3.11 或以上，以及支持插件管理命令的 Codex 桌面版或 CLI。请下载本项目源码，把文件解压到准备长期保留的目录，再在该目录打开 PowerShell。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enable.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\manage.ps1 preview
```

安装脚本会为工具建立独立的 Python 环境，安装 PyYAML，并通过 Codex 注册插件。预览会报告可处理的数量和受保护条目。你可以先看范围，再配置并启动翻译。这里的执行策略只作用于本次 PowerShell 进程。

## 配置并启动翻译

工具通过兼容 OpenAI Responses API 的服务生成译文。如果你的 Codex 已明确配置这类模型服务，工具可以使用对应的模型和凭据。仅在 Codex 中使用 ChatGPT 账号登录时，需要另外提供能直接调用的 Responses API 配置。

下面是 OpenAI API 的配置示例。填入你的 API 密钥前，建议在 Windows **编辑账户的环境变量**里创建 `DESCRIPTION_ZH_API_KEY`，然后重新打开 PowerShell。其他支持 Responses API 的服务可以填各自的地址和模型。

```powershell
$env:DESCRIPTION_ZH_BASE_URL = 'https://api.openai.com/v1'
$env:DESCRIPTION_ZH_MODEL = 'gpt-5-mini'
powershell -NoProfile -ExecutionPolicy Bypass -File .\enable.ps1 -Start
```

- `DESCRIPTION_ZH_BASE_URL` 填 API 根地址，通常以 `/v1` 结尾。工具会加上 `/responses`。
- `DESCRIPTION_ZH_MODEL` 填服务支持的模型。示例使用 `gpt-5-mini`。
- 如果希望每次登录 Windows 后自动运行，可以加 `-AtLogon`。若使用环境变量配置翻译服务，请把所需变量设为**用户环境变量**。当前窗口里的临时设置在重新登录后会失效。
- 启动后，待翻译介绍会发送给你配置的模型服务，可能消耗该服务的额度。详见[数据说明](SECURITY.md)。

## 加入其他插件市场

在 Codex 中添加你信任的市场后，用下面的命令查看实际市场名称。安装的本地插件和个人技能无需选市场就会检查。要翻译**还没有安装**的市场条目，请选中对应市场。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\manage.ps1 markets
.\manage.ps1 markets -Market @('academic-research-skills', 'diagram-design')
```

第二条命令在允许执行本地脚本的 PowerShell 中运行。也可以只选一个市场，使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\manage.ps1 markets -Market diagram-design`。每次设置会替换所选名单。使用 `markets -ClearMarkets` 可取消后续市场扫描，已写入的译文可用 `restore` 恢复。

选中的市场需要有 Codex 提供的可写本地目录。远程 GitHub 条目在公开清单可读取时也可以补充简介。Codex 安装包内置或由账号端动态提供的条目有时仍显示英文。市场列表由 Codex 管理，Git 市场可以用 `codex plugin marketplace upgrade` 刷新。自建本地目录的上游同步由该目录的维护者管理。

## 日常使用

打开 Codex 的插件市场或插件详情看中文说明。在聊天里点名技能时，可编辑的技能简介也会显示中文。列表刚翻译完时，可以关闭并重新打开插件页，或新建一个聊天加载新介绍。

在聊天里可以点名 `$description-zh` 后说「查看汉化状态」。也可以在安装目录运行下表中的命令。如果当前 PowerShell 限制本地脚本，用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\manage.ps1 status` 这种方式执行。

| 想做什么 | 命令 |
|---|---|
| 查看范围，先不翻译 | `.\manage.ps1 preview` |
| 看上次检查结果和失败原因 | `.\manage.ps1 status` |
| 不等后台，立刻检查 | `.\manage.ps1 scan` |
| 允许项目目录下的技能参与翻译 | `.\manage.ps1 scan -Project 'D:\你的项目'` |
| 从后续检查中移除项目 | `.\manage.ps1 projects -RemoveProject 'D:\你的项目'` |
| 暂停或继续 | `.\manage.ps1 pause` 或 `.\manage.ps1 resume` |
| 暂停并恢复英文 | `.\manage.ps1 restore` |
| 退出后台进程 | `.\manage.ps1 stop` |

后台通常每分钟检查一次，Codex 用户目录下的市场文件变更可以提前触发。等待翻译服务及 Codex 刷新列表会增加显示延迟。项目目录需自行加入，默认检查本机用户技能和已安装插件。执行 `stop` 后，用 `enable.ps1 -Start` 重新启动后台。

## 卸载

在安装目录运行下面的命令。它会停止后台、恢复原文、移除与本次安装匹配的开机快捷方式，然后通过 Codex 卸载插件。若某个文件在翻译后又被改过，脚本会显示路径、保留备份并暂停卸载，方便先核对自己的改动。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\disable.ps1
```

本地缓存和备份保存在 `%USERPROFILE%\.codex\description-zh`，设置了 `CODEX_HOME` 时则在对应目录下。上面是备份位置和安装数据目录，清理前请确保原文已恢复。

## 开发与许可

```powershell
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python -B -X utf8 tests/smoke_windows.py
```

最后一条命令使用临时 Codex 目录和本地模拟翻译服务，验证安装、后台检查、市场显示和恢复。需要本机已有支持插件管理的 Codex。此项目用 Codex CLI `0.171.0-alpha.13.2` 做过流程验证。

项目源码采用 [MIT 许可证](LICENSE)。这是社区工具。项目只包含本工具的代码和文档，第三方插件与技能沿用各自的许可证。

**English summary.** Description ZH localizes editable Codex plugin and skill descriptions into Simplified Chinese on Windows. It preserves names and skill instructions, supports opt-in background translation and selected marketplaces, and can restore originals. It requires Python 3.11+ and a compatible Responses API provider for uncached translations.
