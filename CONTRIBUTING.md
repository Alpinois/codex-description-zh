# 参与开发

欢迎提交兼容性修复、安装和恢复流程改进，以及更准确的说明。描述问题时，请附 Windows、Python 和 Codex 的版本、看到的现象，以及经过脱敏的最小复现步骤。

在 Windows 上执行 `python -m pip install -r requirements.txt` 和 `python -B -m unittest discover -s tests -v`。涉及文件改写的改动应验证首次运行、重复运行、源文案更新和恢复。开发时可在独立 PowerShell 窗口用 `CODEX_HOME` 指向临时目录，再安装测试插件。

提交样例时使用虚构的插件和技能说明。第三方市场快照、用户备份和模型凭据留在本机。
