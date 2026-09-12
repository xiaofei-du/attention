# Attention! 📣

<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong> | <a href="README.zh-TW.md">繁體中文</a>
</p>

<p align="center">
  <a href="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml">
    <img src="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml/badge.svg?branch=main&amp;event=push" alt="main 分支的 macOS 测试">
  </a>
  <a href="#环境需求">
    <img src="https://img.shields.io/badge/macOS-14.2%2B-007AFF" alt="macOS 14.2 或更新版本">
  </a>
  <a href="#加入插件">
    <img src="https://img.shields.io/badge/Codex-plugin-17876D" alt="Codex 插件">
  </a>
  <a href="#加入插件">
    <img src="https://img.shields.io/badge/Claude_Code-plugin-D97757" alt="Claude Code 插件">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 许可证">
  </a>
  <a href="#安装">
    <img src="https://img.shields.io/badge/status-alpha-E3A008" alt="Alpha 版本">
  </a>
</p>

<p align="center">
  <a href="https://giphy.com/gifs/cbbc-tracy-beaker-cbbc-star-cYaBD8kxE4PZudHBRA">
    <img src="https://media.giphy.com/media/cYaBD8kxE4PZudHBRA/giphy.gif" alt="CBBC 在 GIPHY 上的 Attention 动图" width="360">
  </a>
</p>

你的 agent 有话想说。

为 **macOS 上的 Codex 和 Claude Code** 提供语音进度通知。每一轮结束后，Attention
会朗读简短回复，或由同一个 agent 写下、像聊天一样的摘要。多个 session 共用一个播放队列。
一位一位来，先别抢话。
语音使用 Mac 已安装的系统音色，不需要另外准备 LLM API key 或云端 TTS 服务。

## 适合谁用？

如果你觉得：

- 原本的通知音，大概跟微波炉差不多，你想要更个性化。
- 同时跑五个 session，每次「叮」一声，都要想「诶，哪个来着？」
- 在家工作，想要一个吵闹的同事。

如果太吵，就跟 agent 说 **「全局关闭语音播报。」** 安静独处也是一项功能。
想听的时候再打开；操作方式见下方的[按你的喜好设置](#按你的喜好设置)。

## 联系我

觉得 Attention 好用，或有什么功能想加？来跟我打个招呼：

[![X: @xiaofeidu283](https://img.shields.io/badge/X-%40xiaofeidu283-9A4329?style=flat-square&logo=x&logoColor=white&labelColor=9A4329)](https://x.com/xiaofeidu283)
[![Threads: @smilefei.du](https://img.shields.io/badge/Threads-%40smilefei.du-9A4329?style=flat-square&logo=threads&logoColor=white&labelColor=9A4329)](https://www.threads.com/@smilefei.du)

## 安装

**Alpha · macOS 14.2+ · Codex 和／或 Claude Code。** 已安装 Homebrew 的话：

```sh
brew install xiaofei-du/tap/attention
attention setup
```

选择 Codex、Claude Code，或两个都装，然后依照[启用并试播](#启用并试播)操作。
Homebrew 会准备好 `uv`；安装向导通过各自的原生插件管理器安装。
既有设置与已禁用的插件都会保留原状。

没有 Homebrew？可以使用[终端安装向导](docs/setup.md#without-homebrew)，
或依照下方的手动步骤操作。不需要下载 ZIP、建立本地 marketplace 文件夹，也不需要自行编译。
安装后，使用 `attention update` 更新已安装且启用的插件，使用 `attention uninstall`
完整移除。详情见 [Homebrew 命令指南](docs/homebrew.md)。

### 环境需求

- **Apple Silicon 或 Intel Mac，macOS 14.2 或更新版本。** CI 在两种架构的 macOS 15
  上测试安装与 hooks。Apple Silicon 已测试实际扬声器播放；Intel 扬声器与其他音频设备仍待测试。
  目前不支持 Windows 和 Linux 播放。
- **Codex 或 Claude Code**，且可在终端执行 `codex` 或 `claude` 命令。
  原生 session 控制已在 Codex CLI 0.154.0 和 Claude Code 2.1.268 上测试；
  较旧的客户端可能需要更新。
- **uv**，终端与 coding app 都必须能找到它。使用 Homebrew 的话：

  ```sh
  brew install uv
  ```

  其他安装方式见 [uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/)。

首次启动会下载 Python 3.12 和固定版本的 MCP 依赖包，因此需要联网，也可能比后续启动慢。
使用预先打包的插件不需要 Xcode。文字播报需要可用的系统音色；如果没有，Attention
会跳过语音，并说明如何下载。

### 加入插件

在终端的任意目录执行以下命令。如果曾安装较早的本地 Alpha 版本，请先参考
[从本地安装切换](docs/upgrading.md#switch-from-a-local-installation)。

执行你使用的客户端所对应的命令。两个都用，就执行两组；它们会共用设置与播放队列。

**Codex**

```sh
codex plugin marketplace add xiaofei-du/attention
codex plugin add attention@xiaofei-du
```

**Claude Code**

```sh
claude plugin marketplace add xiaofei-du/attention
claude plugin install attention@xiaofei-du
```

`xiaofei-du/attention` 是 GitHub repository。`attention@xiaofei-du`
表示从这位发布者的 marketplace 选择 Attention 插件。

### 启用并试播

1. 安装后，重新加载插件或重新开启客户端。
2. **Codex**：在 app 开启 **Hooks**，或在 CLI 输入 `/hooks`，找到
   `attention@xiaofei-du`，分别 Trust **UserPromptSubmit** 和 **Stop**。
   **Claude Code**：插件启用后就会加载 hooks，不需要 Codex 那种逐个 Trust 的步骤。
   重新开启 Claude Code，或执行 `/reload-plugins` 加载新装的插件。
   它还有一个 **PreToolUse** hook，只用来识别 session 控制调用。
3. 开一个新对话，粘贴：

   > Please reply only with: “This is an Attention voice notification.”

   使用全新安装的默认值时，你会先听到 **hey sunshine**，接着是
   **This is an Attention voice notification.** 听到声音才代表播放成功；
   只看到文字还不算。既有语音偏好不会被改动。
4. 输入 **「Attention help」**，查看可调整的设置。

一般播报不需要麦克风或系统音频录制权限。降低其他媒体音量是选配，默认关闭；
启用时可能会要求 macOS 系统音频权限。安装不会修改客户端原本的通知音。

## 按你的喜好设置

替 agent 安排一个出场方式：亲切问候、Mac 提示音，或稍微戏剧化一点。
直接跟 agent 说，就能改设置。以下是操作示例，安装时不会自动执行。

| 想做什么 | 可以这样说 |
| --- | --- |
| 文字开场 | 「把开场改成 hey sunshine。」 |
| Apple 提示音 | 「列出可用的 Apple 开场音效。」然后挑一个。 |
| 自己的音频文件 | 「用这个文件当我的开场音效。」并提供本地音频文件。 |
| 不要开场 | 「移除开场。」 |
| 先报 session 名称 | 「开启 session 名称播报。」 |
| 换个声音 | 「列出已安装的音色。」或「换成男声。」 |
| 降低背景媒体音量 | 「播报时降低 Spotify 和其他媒体的音量。」 |
| 只静音一个 session | 「关闭这个 session 的语音播报。」 |
| 全部静音 | 「全局关闭语音播报。」 |
| 清掉待播通知 | 「清空待播通知队列。」 |
| 只播开场 | 「关闭摘要，只播放开场。」 |
| 调整摘要 | 「控制在 20 秒左右，重点放在下一步。」 |

开场可以是**文字、Apple 内置音效、自定义音频文件，也可以留空**。
自定义音频文件支持 **MP3、WAV、M4A、AIF/AIFF**，上限为 **30 秒／20 MiB**。
Attention 会在本地保存选定音频文件的副本。音频文件会取代文字开场，不会被上传。
设置好的开场会一直保留，直到你再次修改。

**试试这个开场：** [📣 下载「Attention!」音效示例](docs/assets/attention-starter.mp3?raw=1)
（MP3 · 1.7 秒 · 29 KB）。下载后先听听看，再把文件交给 agent，说
**「用这个文件当我的开场音效。」** 这是自定义开场音效，之后仍会接着播报回复或摘要。
想低调，也不是不行。

全局关闭会立即停止播报、清空待播通知，并丢弃关闭期间的新通知。
重新开启后，个别静音的 session 仍然维持静音，也不会补播已取消的通知。
新 session 默认启用，但仍受全局总开关控制。

关闭摘要会同时应用到两个客户端：清除待播通知和暂存摘要，之后只播放开场与选配的 session 名称。
在这个模式下，一般轮次不会注入 Attention hook 提示，也不需要生成摘要。
既有对话会收到一次指令，撤销先前的摘要要求；MCP 工具定义及主动修改设置仍可能使用模型 context。

控制方式、摘要偏好和隐私细节，请见[完整使用指南](packaging/PLUGIN-README.md#getting-started-and-help)（英文）。

## 故障排查

- **没有声音：** 确认插件已加载、hooks 已启用／信任，全局和 session 语音都已开启。
  可以问「显示 Attention 状态。」重新安装时会保留先前的静音设置。
- **找不到 `uv`，或 MCP 启动超时：** 确认 `uv --version` 可正常执行，且 coding app
  能找到它。等依赖包安装完成后重新加载。
- **缺少音色：** [下载 Apple 语音包](#下载-apple-语音包)，再请 Attention 列出音色。
  选择音色不会自动下载或试播。
- **其他媒体还是很大声：** 请 agent 开启降低背景媒体音量，并依照系统权限提示操作。
  Bluetooth 和多输出设备尚未验证。
- **更新现有安装：** 先完成正在进行的任务，再依照[升级指南](docs/upgrading.md)操作。
  重新加载已变更的 hooks，并在系统要求时审核。共用偏好与已导入的开场音频文件都会保留。
- **从旧的 no-keyboard-code 原型迁移：** 移除旧 hooks 前，先依照
  [迁移说明](docs/installation.md#existing-no-keyboard-code-users)操作，以保留设置并避免重复通知。

### 下载 Apple 语音包

1. 开启 **System Settings → Accessibility → Read & Speak**。
   在 macOS Sonoma 14 和 Sequoia 15，这一页叫做 **Spoken Content**。
2. 点击 **System voice** 旁的 **ⓘ**。Sonoma 则使用
   **System voice → Manage Voices**。
3. 选择语言，再选择要下载的音色；Sonoma 请点它旁边的下载按钮。
   保持 Mac 联网，等下载完成后才能使用。各 macOS 版本的步骤可参考
   [Apple 官方语音指南](https://support.apple.com/guide/mac-help/mchlp2290/mac)。
4. 回到 agent，说 **「列出已安装的音色。」** Attention 会刷新音色清单。
   要使用其中一个，可以说 **「使用 [音色名称] 当我的声音。」**，名称请从清单中选择，
   然后再做一次[通知测试](#启用并试播)。

可用语言和音色由 Apple 提供。下载音色不会改变已保存的 Attention 语音偏好。

## 卸载

先完成正在进行的任务，并退出 Codex 和 Claude Code。如果通过 Homebrew 安装，
请在另一个终端执行：

```sh
attention uninstall
```

它会先预览清理内容，要求输入 **yes**，再从两个客户端移除 Attention、清除其数据，
最后移除 Homebrew 命令。取消或清理失败时，命令会保留，方便重试。
共用的 `uv`／Python 和发布者的 tap 会保留。单独执行 `brew uninstall attention`
只会移除命令，插件与语音设置仍然存在。清理自定义设置目录时也会保留命令；
详见 [Homebrew 卸载说明](docs/homebrew.md#uninstall)。

<details>
<summary>没有通过 Homebrew 安装，或已经移除命令？</summary>

请复制[英文 README 中的固定版本卸载命令](README.md#uninstall)。
它会在**执行前**验证下载文件的 SHA-256。三种语言共用这一份命令，避免版本与校验值不同步。

启动脚本会寻找现有 Python 和经验证的本地卸载程序，或依据不可变的 Git 对象 ID
从 GitHub 取得对应程序。它会列出清理路径，并要求输入 **yes**，才从**两个客户端**移除 Attention。

</details>

这会永久删除 Attention 的设置、导入音频文件副本、摘要、队列、日志、专用依赖环境和保留的执行环境。
你的原始音频文件、其他插件、项目、macOS 音色及共用 Python／uv 都会保留。
如果 marketplace 还有其他插件在用，也会保留并提示。
发现未知的嵌套文件、被修改的打包文件，或不安全的目录所有权时，
清理会在调用原生卸载命令前停止。请把提示中的个人文件移到 Attention 目录外，再重试；
没有强制删除选项。请勿以 sudo 执行。

<details>
<summary>预览、离线移除、自定义设置目录与单一客户端卸载</summary>

每个插件包都包含 `uninstall.sh`。在源码或插件包目录中，可以先预览，不删除任何内容：

```sh
bash -p uninstall.sh --dry-run --offline
```

执行 `bash -p uninstall.sh --offline`，即可在本地预览并确认。命令不需要填版本号。
如果将脚本另存到其他位置，它也会在常见的 Codex／Claude 插件缓存和 Attention 保留的执行环境中
寻找相符的卸载程序。`--offline` 不允许任何下载。旧版启动脚本必须使用相符的卸载程序；
校验值不符时，会在执行卸载程序前停止。

启动脚本使用现有的 **Python 3.11+**（包括符合版本要求的 Conda Python），
或请 uv 寻找已安装的 Python 3.12。它不会安装 Python、SDK 依赖包或音效库。
如果两者都不可用，请恢复 Attention 原本使用的 Python 后重试。
只使用可信来源的启动脚本；SHA-256 校验可以发现程序被修改或版本不符，
但无法防范发布者账号遭入侵。线上命令还会依英文 README 中的校验值，另行验证外层启动脚本。
你仍然需要信任这些说明与本地可执行程序；这并不是发布者签名。
固定的 Git 对象 ID 不会跟随 `main` 变动；遇到 GitHub API 速率限制或对象丢失时，下载会安全停止。

清理依照精确的文件清单进行，不会递归删除清理过程中新加入的文件。
原生客户端命令自行管理它们的缓存；卸载程序在调用前会再次检查，
但无法将这些命令，或以你的用户身份执行且已遭入侵的程序，限制在沙箱内。
移除期间请保持两个客户端都已关闭。

只有确定要跳过确认时才使用 `--yes`；通过管道传入 `echo yes` 不会回答默认的终端确认提示。
也可直接执行 `python3 -I scripts/uninstall.py --dry-run`，或使用 `--yes`。
执行 `bash uninstall.sh --help` 查看启动脚本选项。

请使用与安装时相同的 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 和 `ATTENTION_DATA_DIR`
覆盖值。`--data-dir PATH` 也能指定 Attention 的自定义数据根目录。
清除共用数据前，其他自定义设置目录中的安装必须分别移除。
旧版 no-keyboard-code hooks 需要先迁移或移除。

仍在执行的 MCP／hook session 会阻止删除。后台播放 worker 会收到全局关闭信号，
必须退出后才能删除文件。客户端移除失败、仍有插件注册，或清理范围发生变化，都会停止操作；
请修正提示的问题后重试。只要该客户端仍装有 Attention，对应的 CLI 就必须保持可用。
如果下载时证书验证失败，请改用本地副本，不要关闭 TLS 验证。

如果只想从**一个客户端**移除 Attention，保留共用设置与音频文件：

```sh
codex plugin remove attention@xiaofei-du
# or
claude plugin uninstall attention@xiaofei-du
```

之后重新启动该客户端。单一客户端卸载命令会保留共用数据，
也不会停止已经在播放的 worker。客户端对话记录、操作系统权限记录和备份
由各自宿主程序管理，不在 Attention 卸载命令的清理范围内。

</details>

## 参与贡献

Semantic commit、PR 说明格式与验证要求，请见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 从源码构建

只有从源码构建才需要 **Xcode 26 或更新版本**，以及 macOS 26 SDK（`xcrun` 和 `clang`）。
较新的 SDK 用来编译具有 macOS 26 版本保护的 API；最低部署版本仍为 macOS 14.2。
在 repository 根目录执行：

```sh
uv run --no-config --no-project --isolated --python 3.12 python scripts/build_marketplace.py --output .build/attention-marketplace
```

这会产生两个客户端的插件包与目录信息。构建程序要求使用新的输出目录；
再次构建时，请改用另一个 `--output` 路径。发布源码修改前，
请用产生的版本替换已提交的 `plugins/`、`claude-plugins/`、
`.agents/plugins/marketplace.json` 和 `.claude-plugin/marketplace.json`。
分发包测试会检查是否仍有过期的运行程序副本。

执行开发测试时，回到 repository 根目录：

```sh
uv lock --check
uv venv --managed-python --python 3.12 .venv
uv pip sync --python .venv/bin/python --require-hashes --only-binary :all: --find-links packaging/wheels --index-url https://pypi.org/simple packaging/requirements.txt
ATTENTION_TEST_MARKETPLACE="$PWD" .venv/bin/python -m unittest discover -s tests -v
```

测试使用可丢弃的独立数据与静音播放替身。主机沙箱诊断测试需要另外启用，
这个命令不会自动执行它们。

原生可执行文件目前使用 ad-hoc 签名，尚未取得 Developer ID 公证。
Alpha 版本仍需要全新电脑和更多音频设备的测试，才能成为稳定版本。
[安全边界](docs/security-boundaries.md)说明了已验证与尚未验证的部分。

## 许可证

Attention 的代码与文档采用 [MIT License](LICENSE)。
第三方依赖包、示范音频文件与链接的 GIF，仍适用各自的授权与权利。
