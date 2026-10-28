# 微信 AI 机器人（开源整理草稿）

Windows 桌面微信机器人：基于微信桌面客户端和 `wechatauto-replica` 读取消息，并使用兼容 OpenAI 接口格式的服务生成回复。支持私聊、群聊接话、搜索、图片和表情处理，以及可选的语音、拍一拍、视频理解和唱歌功能。

**当前是待发布草稿。** 自动回复功能依赖微信版本、桌面界面、数据库访问权限和外部服务；尚未在全新电脑上完成完整部署验证。不要把 `.env`、联系人配置、聊天记录、图片或日志上传到公开仓库。

首次使用请看 [Windows 新手部署教程](docs/新手部署教程.md)，其中包含示意图、逐步操作和常见问题。

## 基础准备

1. 使用 Windows、Python 3.12，安装并登录兼容的桌面微信。依赖微信的本机数据库和桌面界面，微信版本变化可能导致部分功能失效。
2. 准备 DeepSeek API 密钥；调用会由服务商计费。请核对服务提供商支持的模型名称和功能。
3. 在项目目录运行 PowerShell：

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   if (Test-Path .env) { Write-Host '配置已存在，请先检查，不会覆盖。' } else { Copy-Item .env.example .env }
   ```

4. 编辑 `.env`，填写自己的密钥、模型和测试联系人。`PRIVATE_MODE=test` 只限制私聊的测试好友；群聊范围由 `GROUP_NAMES` 另行控制，多个群名用英文逗号分隔，留空允许所有群。默认 `ENABLE_SEND=0`，预览时仍会调用模型。确认连接和设置后，才按需设置 `ENABLE_SEND=1`。
5. 启动：

   ```powershell
   .\.venv\Scripts\python.exe bot.py
   ```

如果微信有多个账号，请先确认 `bot_account.py` 的账号绑定逻辑适用于你的环境。`称呼配置.json` 是本机私有文件，不随项目提供；未配置时不会绑定特殊联系人。

## 可选功能

- **原生语音和唱歌**：分别安装 `requirements-voice.txt`、`requirements-singing.txt`；原生语音依赖 VB-CABLE 及 Windows 麦克风权限。唱歌另需开通云服务并自行配置密钥；服务费用和实际演唱效果由服务商决定。
- **视频理解**：安装 `requirements-video.txt`，并自行提供 FFmpeg/ffprobe 和 `video_tools.py` 指定的本地 faster-whisper 模型。模型不随仓库分发，本草稿还没有提供自动下载流程。
- **图片理解**：`ENABLE_VISION_UPLOAD=1` 会将所选图像画面交给配置的模型服务处理，模型必须支持图像输入。先确认服务商的数据处理方式，默认关闭。
- **主动拍一拍**：默认关闭，可用 `ENABLE_PROACTIVE_PAT=1` 启用。开启自动发送前先在受控环境验证。

## 重要限制

当前代码包含针对特定微信版本和界面布局的自动化；视频、表情、@、语音和拍一拍可能因客户端版本或系统设置而不可用。项目使用的 `wechatauto-replica` 是独立的第三方依赖，遵循其自身的许可证；本仓库不包含或重新许可该依赖的源码。

## 许可

项目代码拟使用 [MIT License](LICENSE)。第三方依赖、模型、音频和图片各自遵循其原有许可。
