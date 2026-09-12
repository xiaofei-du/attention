# Attention! 📣

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <strong>繁體中文</strong>
</p>

<p align="center">
  <a href="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml">
    <img src="https://github.com/xiaofei-du/attention/actions/workflows/tests.yml/badge.svg?branch=main&amp;event=push" alt="main 分支的 macOS 測試">
  </a>
  <a href="#環境需求">
    <img src="https://img.shields.io/badge/macOS-14.2%2B-007AFF" alt="macOS 14.2 或更新版本">
  </a>
  <a href="#加入插件">
    <img src="https://img.shields.io/badge/Codex-plugin-17876D" alt="Codex 插件">
  </a>
  <a href="#加入插件">
    <img src="https://img.shields.io/badge/Claude_Code-plugin-D97757" alt="Claude Code 插件">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 授權條款">
  </a>
  <a href="#安裝">
    <img src="https://img.shields.io/badge/status-alpha-E3A008" alt="Alpha 版本">
  </a>
</p>

<p align="center">
  <a href="https://giphy.com/gifs/cbbc-tracy-beaker-cbbc-star-cYaBD8kxE4PZudHBRA">
    <img src="https://media.giphy.com/media/cYaBD8kxE4PZudHBRA/giphy.gif" alt="CBBC 在 GIPHY 上的 Attention 動圖" width="360">
  </a>
</p>

你的 agent 有話想說。

為 **macOS 上的 Codex 和 Claude Code** 提供語音進度通知。每一輪結束後，Attention
會朗讀簡短回覆，或由同一個 agent 寫下、像聊天一樣的摘要。多個 session 共用一個播放佇列。
一位一位來，先別搶話。
語音使用 Mac 已安裝的系統音色，不需要另外準備 LLM API key 或雲端 TTS 服務。

## 適合誰用？

如果你有以下感受，歡迎入座：

- 原本的通知音，個性大概跟微波爐差不多。
- 同時跑五個 session，每次「叮」一聲，都要玩一輪「剛剛是哪個？」
- 在家工作，想要一個可以按靜音的同事。

如果太吵，就跟 agent 說 **「全域關閉語音播報。」** 安靜獨處也是一項功能。
想聽的時候再打開；操作方式見下方的[按你的喜好設定](#按你的喜好設定)。

## 聯絡我

覺得 Attention 好用，或有什麼功能想加？來跟我打個招呼：

[![X: @xiaofeidu283](https://img.shields.io/badge/X-%40xiaofeidu283-9A4329?style=flat-square&logo=x&logoColor=white&labelColor=9A4329)](https://x.com/xiaofeidu283)
[![Threads: @smilefei.du](https://img.shields.io/badge/Threads-%40smilefei.du-9A4329?style=flat-square&logo=threads&logoColor=white&labelColor=9A4329)](https://www.threads.com/@smilefei.du)

## 安裝

**Alpha · macOS 14.2+ · Codex 和／或 Claude Code。** 已安裝 Homebrew 的話：

```sh
brew install xiaofei-du/tap/attention
attention setup
```

選擇 Codex、Claude Code，或兩個都裝，然後依照[啟用並試播](#啟用並試播)操作。
Homebrew 會準備好 `uv`；安裝精靈透過各自的原生插件管理器安裝。
既有設定與已停用的插件都會保留原狀。

沒有 Homebrew？可以使用[終端機安裝精靈](docs/setup.md#without-homebrew)，
或依照下方的手動步驟操作。不需要下載 ZIP、建立本機 marketplace 資料夾，也不需要自行編譯。
安裝後，使用 `attention update` 更新已安裝且啟用的插件，使用 `attention uninstall`
完整移除。詳情見 [Homebrew 命令指南](docs/homebrew.md)。

### 環境需求

- **Apple Silicon 或 Intel Mac，macOS 14.2 或更新版本。** CI 在兩種架構的 macOS 15
  上測試安裝與 hooks。Apple Silicon 已測試實際喇叭播放；Intel 喇叭與其他音訊裝置仍待測試。
  目前不支援 Windows 和 Linux 播放。
- **Codex 或 Claude Code**，且可在終端機執行 `codex` 或 `claude` 命令。
  原生 session 控制已在 Codex CLI 0.154.0 和 Claude Code 2.1.268 上測試；
  較舊的客戶端可能需要更新。
- **uv**，終端機與 coding app 都必須能找到它。使用 Homebrew 的話：

  ```sh
  brew install uv
  ```

  其他安裝方式見 [uv 安裝指南](https://docs.astral.sh/uv/getting-started/installation/)。

首次啟動會下載 Python 3.12 和固定版本的 MCP 相依套件，因此需要連網，也可能比後續啟動慢。
使用預先打包的插件不需要 Xcode。文字播報需要可用的系統音色；如果沒有，Attention
會略過語音，並說明如何下載。

### 加入插件

在終端機的任意目錄執行以下命令。如果曾安裝較早的本機 Alpha 版本，請先參考
[從本機安裝切換](docs/upgrading.md#switch-from-a-local-installation)。

執行你使用的客戶端所對應的命令。兩個都用，就執行兩組；它們會共用設定與播放佇列。

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
表示從這位發布者的 marketplace 選取 Attention 插件。

### 啟用並試播

1. 安裝後，重新載入插件或重新開啟客戶端。
2. **Codex**：在 app 開啟 **Hooks**，或在 CLI 輸入 `/hooks`，找到
   `attention@xiaofei-du`，分別 Trust **UserPromptSubmit** 和 **Stop**。
   **Claude Code**：插件啟用後就會載入 hooks，不需要 Codex 那種逐個 Trust 的步驟。
   重新開啟 Claude Code，或執行 `/reload-plugins` 載入新裝的插件。
   它還有一個 **PreToolUse** hook，只用來識別 session 控制呼叫。
3. 開一個新對話，貼上：

   > Please reply only with: “This is an Attention voice notification.”

   使用全新安裝的預設值時，你會先聽到 **hey sunshine**，接著是
   **This is an Attention voice notification.** 聽到聲音才代表播放成功；
   只看到文字還不算。既有語音偏好不會被改動。
4. 輸入 **「Attention help」**，查看可調整的設定。

一般播報不需要麥克風或系統音訊錄製權限。降低其他媒體音量是選配，預設關閉；
啟用時可能會要求 macOS 系統音訊權限。安裝不會修改客戶端原本的通知音。

## 按你的喜好設定

替 agent 安排一個出場方式：親切問候、Mac 提示音，或稍微戲劇化一點。
直接跟 agent 說，就能改設定。以下是操作範例，安裝時不會自動執行。

| 想做什麼 | 可以這樣說 |
| --- | --- |
| 文字開場 | 「把開場改成 hey sunshine。」 |
| Apple 提示音 | 「列出可用的 Apple 開場音效。」然後挑一個。 |
| 自己的音檔 | 「用這個檔案當我的開場音效。」並提供本機音檔。 |
| 不要開場 | 「移除開場。」 |
| 先報 session 名稱 | 「開啟 session 名稱播報。」 |
| 換個聲音 | 「列出已安裝的音色。」或「換成男聲。」 |
| 降低背景媒體音量 | 「播報時降低 Spotify 和其他媒體的音量。」 |
| 只靜音一個 session | 「關閉這個 session 的語音播報。」 |
| 全部靜音 | 「全域關閉語音播報。」 |
| 清掉待播通知 | 「清空待播通知佇列。」 |
| 只播開場 | 「關閉摘要，只播放開場。」 |
| 調整摘要 | 「控制在 20 秒左右，重點放在下一步。」 |

開場可以是**文字、Apple 內建音效、自訂音檔，也可以留空**。
自訂音檔支援 **MP3、WAV、M4A、AIF/AIFF**，上限為 **30 秒／20 MiB**。
Attention 會在本機保存選定音檔的副本。音檔會取代文字開場，不會被上傳。
設定好的開場會一直保留，直到你再次修改。

**試試這個開場：** [📣 下載「Attention!」音效範例](docs/assets/attention-starter.mp3?raw=1)
（MP3 · 1.7 秒 · 29 KB）。下載後先聽聽看，再把檔案交給 agent，說
**「用這個檔案當我的開場音效。」** 這是自訂開場音效，之後仍會接著播報回覆或摘要。
想低調，也不是不行。

全域關閉會立即停止播報、清空待播通知，並丟棄關閉期間的新通知。
重新開啟後，個別靜音的 session 仍然維持靜音，也不會補播已取消的通知。
新 session 預設啟用，但仍受全域總開關控制。

關閉摘要會同時套用到兩個客戶端：清除待播通知和暫存摘要，之後只播放開場與選配的 session 名稱。
在這個模式下，一般輪次不會注入 Attention hook 提示，也不需要生成摘要。
既有對話會收到一次指令，撤銷先前的摘要要求；MCP 工具定義及主動修改設定仍可能使用模型 context。

控制方式、摘要偏好和隱私細節，請見[完整使用指南](packaging/PLUGIN-README.md#getting-started-and-help)（英文）。

## 疑難排解

- **沒有聲音：** 確認插件已載入、hooks 已啟用／信任，全域和 session 語音都已開啟。
  可以問「顯示 Attention 狀態。」重新安裝時會保留先前的靜音設定。
- **找不到 `uv`，或 MCP 啟動逾時：** 確認 `uv --version` 可正常執行，且 coding app
  能找到它。等相依套件安裝完成後重新載入。
- **缺少音色：** [下載 Apple 語音包](#下載-apple-語音包)，再請 Attention 列出音色。
  選擇音色不會自動下載或試播。
- **其他媒體還是很大聲：** 請 agent 開啟降低背景媒體音量，並依照系統權限提示操作。
  Bluetooth 和多輸出裝置尚未驗證。
- **更新現有安裝：** 先完成正在進行的任務，再依照[升級指南](docs/upgrading.md)操作。
  重新載入已變更的 hooks，並在系統要求時審核。共用偏好與已匯入的開場音檔都會保留。
- **從舊的 no-keyboard-code 原型遷移：** 移除舊 hooks 前，先依照
  [遷移說明](docs/installation.md#existing-no-keyboard-code-users)操作，以保留設定並避免重複通知。

### 下載 Apple 語音包

1. 開啟 **System Settings → Accessibility → Read & Speak**。
   在 macOS Sonoma 14 和 Sequoia 15，這一頁叫做 **Spoken Content**。
2. 點選 **System voice** 旁的 **ⓘ**。Sonoma 則使用
   **System voice → Manage Voices**。
3. 選擇語言，再選擇要下載的音色；Sonoma 請點它旁邊的下載按鈕。
   保持 Mac 連網，等下載完成後才能使用。各 macOS 版本的步驟可參考
   [Apple 官方語音指南](https://support.apple.com/guide/mac-help/mchlp2290/mac)。
4. 回到 agent，說 **「列出已安裝的音色。」** Attention 會重新整理音色清單。
   要使用其中一個，可以說 **「使用 [音色名稱] 當我的聲音。」**，名稱請從清單中選取，
   然後再做一次[通知測試](#啟用並試播)。

可用語言和音色由 Apple 提供。下載音色不會改變已儲存的 Attention 語音偏好。

## 解除安裝

先完成正在進行的任務，並退出 Codex 和 Claude Code。如果透過 Homebrew 安裝，
請在另一個終端機執行：

```sh
attention uninstall
```

它會先預覽清理內容，要求輸入 **yes**，再從兩個客戶端移除 Attention、清除其資料，
最後移除 Homebrew 命令。取消或清理失敗時，命令會保留，方便重試。
共用的 `uv`／Python 和發布者的 tap 會保留。單獨執行 `brew uninstall attention`
只會移除命令，插件與語音設定仍然存在。清理自訂設定目錄時也會保留命令；
詳見 [Homebrew 解除安裝說明](docs/homebrew.md#uninstall)。

<details>
<summary>沒有透過 Homebrew 安裝，或已經移除命令？</summary>

請複製[英文 README 中的固定版本卸載命令](README.md#uninstall)。
它會在**執行前**驗證下載檔案的 SHA-256。三種語言共用這一份命令，避免版本與校驗值不同步。

啟動腳本會尋找現有 Python 和經驗證的本機卸載程式，或依據不可變的 Git 物件 ID
從 GitHub 取得對應程式。它會列出清理路徑，並要求輸入 **yes**，才從**兩個客戶端**移除 Attention。

</details>

這會永久刪除 Attention 的設定、匯入音檔副本、摘要、佇列、日誌、專用相依環境和保留的執行環境。
你的原始音檔、其他插件、專案、macOS 音色及共用 Python／uv 都會保留。
如果 marketplace 還有其他插件在用，也會保留並提示。
發現未知的巢狀檔案、被修改的打包檔案，或不安全的目錄擁有權時，
清理會在呼叫原生卸載命令前停止。請把提示中的個人檔案移到 Attention 目錄外，再重試；
沒有強制刪除選項。請勿以 sudo 執行。

<details>
<summary>預覽、離線移除、自訂設定目錄與單一客戶端卸載</summary>

每個插件套件都包含 `uninstall.sh`。在原始碼或插件套件目錄中，可以先預覽，不刪除任何內容：

```sh
bash -p uninstall.sh --dry-run --offline
```

執行 `bash -p uninstall.sh --offline`，即可在本機預覽並確認。命令不需要填版本號。
如果將腳本另存到其他位置，它也會在常見的 Codex／Claude 插件快取和 Attention 保留的執行環境中
尋找相符的卸載程式。`--offline` 不允許任何下載。舊版啟動腳本必須使用相符的卸載程式；
校驗值不符時，會在執行卸載程式前停止。

啟動腳本使用現有的 **Python 3.11+**（包括符合版本要求的 Conda Python），
或請 uv 尋找已安裝的 Python 3.12。它不會安裝 Python、SDK 相依套件或音效函式庫。
如果兩者都不可用，請恢復 Attention 原本使用的 Python 後重試。
只使用可信來源的啟動腳本；SHA-256 校驗可以發現程式被修改或版本不符，
但無法防範發布者帳號遭入侵。線上命令還會依英文 README 中的校驗值，另行驗證外層啟動腳本。
你仍然需要信任這些說明與本機可執行程式；這並不是發布者簽章。
固定的 Git 物件 ID 不會跟隨 `main` 變動；遇到 GitHub API 流量限制或物件遺失時，下載會安全停止。

清理依照精確的檔案清單進行，不會遞迴刪除清理過程中新加入的檔案。
原生客戶端命令自行管理它們的快取；卸載程式在呼叫前會再次檢查，
但無法將這些命令，或以你的使用者身分執行且已遭入侵的程序，限制在沙箱內。
移除期間請保持兩個客戶端都已關閉。

只有確定要略過確認時才使用 `--yes`；透過管線傳入 `echo yes` 不會回答預設的終端機確認提示。
也可直接執行 `python3 -I scripts/uninstall.py --dry-run`，或使用 `--yes`。
執行 `bash uninstall.sh --help` 查看啟動腳本選項。

請使用與安裝時相同的 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 和 `ATTENTION_DATA_DIR`
覆寫值。`--data-dir PATH` 也能指定 Attention 的自訂資料根目錄。
清除共用資料前，其他自訂設定目錄中的安裝必須分別移除。
舊版 no-keyboard-code hooks 需要先遷移或移除。

仍在執行的 MCP／hook session 會阻止刪除。背景播放 worker 會收到全域關閉訊號，
必須退出後才能刪除檔案。客戶端移除失敗、仍有插件註冊，或清理範圍發生變化，都會停止操作；
請修正提示的問題後重試。只要該客戶端仍裝有 Attention，對應的 CLI 就必須保持可用。
如果下載時憑證驗證失敗，請改用本機副本，不要關閉 TLS 驗證。

如果只想從**一個客戶端**移除 Attention，保留共用設定與音檔：

```sh
codex plugin remove attention@xiaofei-du
# or
claude plugin uninstall attention@xiaofei-du
```

之後重新啟動該客戶端。單一客戶端卸載命令會保留共用資料，
也不會停止已經在播放的 worker。客戶端對話紀錄、作業系統權限紀錄和備份
由各自主程式管理，不在 Attention 卸載命令的清理範圍內。

</details>

## 參與貢獻

Semantic commit、PR 說明格式與驗證要求，請見 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 從原始碼建置

只有從原始碼建置才需要 **Xcode 26 或更新版本**，以及 macOS 26 SDK（`xcrun` 和 `clang`）。
較新的 SDK 用來編譯具有 macOS 26 版本保護的 API；最低部署版本仍為 macOS 14.2。
在 repository 根目錄執行：

```sh
uv run --no-config --no-project --isolated --python 3.12 python scripts/build_marketplace.py --output .build/attention-marketplace
```

這會產生兩個客戶端的插件套件與目錄資訊。建置程式要求使用新的輸出目錄；
再次建置時，請改用另一個 `--output` 路徑。發布原始碼修改前，
請用產生的版本替換已提交的 `plugins/`、`claude-plugins/`、
`.agents/plugins/marketplace.json` 和 `.claude-plugin/marketplace.json`。
發佈套件測試會檢查是否仍有過期的執行程式副本。

執行開發測試時，回到 repository 根目錄：

```sh
uv lock --check
uv venv --managed-python --python 3.12 .venv
uv pip sync --python .venv/bin/python --require-hashes --only-binary :all: --find-links packaging/wheels --index-url https://pypi.org/simple packaging/requirements.txt
ATTENTION_TEST_MARKETPLACE="$PWD" .venv/bin/python -m unittest discover -s tests -v
```

測試使用可丟棄的獨立資料與靜音播放替身。主機沙箱診斷測試需要另外啟用，
這個命令不會自動執行它們。

原生執行檔目前使用 ad-hoc 簽署，尚未取得 Developer ID 公證。
Alpha 版本仍需要全新電腦和更多音訊裝置的測試，才能成為穩定版本。
[安全邊界](docs/security-boundaries.md)說明了已驗證與尚未驗證的部分。

## 授權條款

Attention 的程式碼與文件採用 [MIT License](LICENSE)。
第三方相依套件、示範音檔與連結的 GIF，仍適用各自的授權與權利。
