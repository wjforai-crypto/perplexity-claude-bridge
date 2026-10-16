# Perplexity Claude Bridge

把已登录的 Perplexity 网页账户接到支持 Anthropic Messages API 的本地客户端，补齐附件传递、客户端工具调用和长请求处理。主要验证环境为 **Windows + Claude Code / Claude Desktop 的 Code 页 + CC Switch**。

这是基于 [jacob-bd/perplexity-web-mcp](https://github.com/jacob-bd/perplexity-web-mcp) 的独立适配层。上游作为固定版本依赖安装，本仓库包含新增与改写的桥接代码、安装脚本和离线测试。项目与 Perplexity、Anthropic 均无官方关联。

## 解决什么问题

- **HTTP 414**：初始化 GET 使用短查询，实际对话继续放在 POST 正文里。
- **附件丢失**：保留文字、图片、PDF、MP4 等内容，并通过上游原生文件上传机制发送。
- **本地文件不可读**：把模型提出的动作转换成客户端 `tool_use`，由 Claude 客户端实际执行 Read、Write、Bash 等工具，再传回 `tool_result`。
- **大量工具说明挤占请求**：较大请求的完整上下文放入临时文本附件，提示中保留近期会话和常用工具 schema。
- **Windows 中文乱码**：文件辅助程序固定输出 UTF-8。

```text
Claude Code / Claude Desktop Code
        │ Anthropic Messages API
        ▼
CC Switch（可选）
        ▼
127.0.0.1:18080 → 本地适配层 → Perplexity 网页接口
        │
        └─ tool_use 返回客户端 → 客户端执行 → tool_result
```

代理不会自行执行模型生成的命令。实际文件读写与命令执行仍由客户端管理权限。

## Windows 安装

需要 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 PowerShell 7。安装脚本创建独立 Python 3.12 环境，不修改已有 Claude 或 CC Switch 配置。

```powershell
git clone https://github.com/wjforai-crypto/perplexity-claude-bridge.git
cd perplexity-claude-bridge
pwsh -NoProfile -File .\setup.ps1
pwsh -NoProfile -File .\login.ps1
pwsh -NoProfile -File .\start.ps1
```

在本机登录窗口填写 Perplexity 邮箱与邮件验证码。验证码和会话 Token 不需要交给其他人。账户需要拥有目标模型的使用权限；本仓库没有绕过订阅或额度限制的功能。

首次安装会生成 `private/api-key.txt`。Windows 下 `private/` 的继承权限会被关闭，仅授予当前用户和 SYSTEM 访问权限；文件不会进入 Git。重复安装不会轮换已有密钥。

停止代理：

```powershell
pwsh -NoProfile -File .\stop.ps1
```

默认仅监听 `127.0.0.1:18080`。启动/停止脚本会核对进程是否属于当前安装目录，遇到其他程序或另一份安装占用端口会报错。没有配置开机自启，重启电脑后需要再次启动代理。登录失效时重新运行 `login.ps1`，随后停止并启动代理。

## 接入 CC Switch / Claude

在 CC Switch 为目标客户端新增供应商，选择 **Anthropic** 接口格式：

| 配置 | 值 |
|---|---|
| Base URL | `http://127.0.0.1:18080` |
| API Key | 本机 `private/api-key.txt` 中的内容 |
| 主模型 | `claude-opus-5-5` |
| 次模型 | `claude-sonnet-5-5` |

只在自己的客户端设置中填写密钥，不要把填好的配置提交到仓库。占位示例见 [examples/provider.json](examples/provider.json)。如果当前 CC Switch 提供 Claude Desktop 模型角色映射，可将 Opus 角色映射到 `claude-opus-5-5`，Sonnet 角色映射到 `claude-sonnet-5-5`。如将辅助角色也映射到 Sonnet，应明确标注其实际模型，不把它宣称为 Haiku。

启用该供应商，按客户端要求重新启动 Claude。使用 Claude Desktop 时优先在 **Code 页新建会话**。普通聊天页、Cowork 和不同客户端版本不作兼容承诺。

| 本地模型 ID | Perplexity ID | 启用 thinking 时 |
|---|---|---|
| `claude-opus-5-5` | `claude55opus` | `claude55opusthinking` |
| `claude-sonnet-5-5` | `claude55sonnet` | `claude55sonnetthinking` |

这组标识在原安装环境中核对过，但上游目录可能变化。未知模型被明确拒绝，不静默切换其他模型。路由标识和模型自我介绍都不能独立证明服务商底层运行的模型。

## 文件与视频

在 Code 页通过 **＋ → Add files or photos** 选择附件，或提供完整本地路径。文本和图片通常由 Read 读取；视频等二进制文件可由 Bash 调用 `file_question.py`，上传后返回分析。适配器会自动把本次安装的 Python 和辅助程序路径告知模型。

例如：

> 请先实际读取交接文档和视频附件，概述你看见的内容，再给出下一步方案。视频需要上传分析时使用本地文件辅助程序。

也可以手动运行：

```powershell
.\.venv\Scripts\python.exe .\file_question.py --file 'C:/path/to/video.mp4' --prompt '按时间顺序描述画面变化' --model claude-opus-5-5
```

只显示附件卡片不代表模型已经读取；应检查实际工具调用和分析结果。

## 范围与限制

- 本仓库依赖非官方网页接口。站点更新、验证码、会话失效或限流可能影响可用性。
- 仅 `/v1/messages` 使用新适配层；上游 OpenAI 兼容端点没有同步改造，不宣称支持同等附件或工具能力。
- 工具调用通过 JSON 协议模拟，每次回复最多一个工具；工具名称和参数必须通过注册 schema 校验。格式错误最多重试一次，仍不合法则报错。
- 原生 Anthropic 工具调用、思考签名、Effort、`max_tokens` 等行为不能视为完全等价；页面 token/费用是估计值，不是 Perplexity 账单。
- 单附件最多 **50 MiB**，总附件 **100 MiB**，最多 **30** 个不同附件；完整上下文文件会占用一个附件位置。云端 `file_id` 和 URL 引用不自动下载，缺少真实内容会报错。
- 超过约 **45,000 字符**的完整请求使用文本附件承载，超过 **600,000 字符**明确拒绝。附件检索不等于原生完整长上下文，也不保证每个历史细节都被模型使用。
- 模型返回的完整 JSON 经校验后才转成 SSE，等待时每 5 秒发心跳，因此不是真正逐 token 转发。
- MP4 验证使用短合成视频；真实长视频、音轨、Cowork、复杂多工具工程未完成全面验收。大视频可抽帧，但应明确只分析了样本帧。
- 使用时客户端发来的系统说明、工具定义、会话内容及附件会发送到 Perplexity。临时上传文件保存在 `private/bridge-temp/` 并在请求结束后清理；异常强制终止时可能留下文件。
- MIT 许可适用于本仓库代码，不替代 Perplexity 和客户端自身的服务条款。

## 查询用量

```powershell
.\.venv\Scripts\python.exe .\pwm_local.py usage --refresh
```

返回账户当时提供的计数。模型单独剩余次数可能不公开；不要把搜索次数、Computer 积分和 API 余额混算。该命令输出的账户数据也不应提交到 GitHub。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe .\tests\run.py
```

离线测试使用模拟上游和临时密钥，不需要真实登录，不消耗订阅额度。涵盖内容保留、附件清理、工具参数校验、SSE、鉴权、精确模型路由、HTTP 414 修复、完整上下文附件、安装可迁移性与 UTF-8 输出。详见 [docs/VALIDATION.md](docs/VALIDATION.md)。

## 来源与许可证

MIT；原作者版权和许可全文保留在 [LICENSE](LICENSE)。固定上游提交及协议参考见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。不包含第三方客户端程序、运行时凭据或私人会话数据。
