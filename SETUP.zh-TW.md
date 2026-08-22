# 安裝 — 從 clone 到第一支通過閘門的影片

<p align="center"><a href="SETUP.md">English</a> · 繁體中文</p>

設計目標很簡單：剛 clone 下來的乾淨環境，有 ffmpeg 和兩個 Python 套件就能跑完整條線。其他每一項都只解鎖一個額外功能，缺了就乾淨跳過，不會報錯。

這份是給人看的散文版。版本號、參數預設值、flag 清單、工具對照表這些機器事實，一律以 [SETUP.md](SETUP.md) 為準，我不在這裡重抄一遍。同一個數字寫在兩個地方，遲早會有一份是錯的。

文件本身也會過期。這個指令不會：

```bash
python3 doctor.py
```

它會逐項檢查這台機器有什麼、缺什麼，並且把該執行的安裝指令直接印出來。第一次先跑它，每次裝完東西再跑它。它跟文件不一致的時候，信它。

## Tier 0 — 必要（每一次算圖、每一道閘門都要）

只有四樣：Python 3.9+、ffmpeg（含 ffprobe）、Pillow、numpy。安裝指令見 [SETUP.md Tier 0](SETUP.md#tier-0--required-every-render-every-gate)，或直接照 `doctor.py` 印的做。

字幕字型（演示斜黑体）已經內建在 `assets/fonts/`，不用另外裝。

平台方面有一個限制要先講。口播管線（`postprod.py`）是跨平台的，macOS 用硬體編碼，其他系統自動退回軟體編碼。但模板模式用的 `modules/buildkit.py` 目前寫死了 macOS 的 videotoolbox，所以 agent 組裝的模板 build 現階段只能在 macOS 跑，Linux 上要自己寫最後的編碼步驟。

## Tier 1 — 語音字幕（faster-whisper，裝在 venv 裡）

ASR 跑在這個 skill 自己的 venv 裡，重量級依賴永遠不會碰到你的系統 Python。Gemini 和 OpenAI 的 SDK 呼叫也走同一個 venv，一個 venv 兩邊都服務到。

指令見 [SETUP.md Tier 1](SETUP.md#tier-1--speech-captions-faster-whisper-in-a-venv)。想要去背版面（把講者去背站在素材前面）的話，同一行加上 `mediapipe`；沒裝的話輪播版面就只是跳過那幾種變化，不會出錯。

第一次轉寫會下載 Whisper 模型，`large-v3` 大約 3 GB。記憶體吃緊就在 `config.py` 把模型降到 `medium`。沒有 venv 也還是能跑，只是語音字幕那部分會被跳過。

## Tier 2 — API 金鑰（每把鑰匙解鎖一個功能，全部都不是必要的）

金鑰檔是一行、純鑰匙、不加引號、不加 `KEY=` 前綴，放在 skill 根目錄。你 clone 到哪就是哪：程式是相對自己的位置找檔案，不是找固定安裝路徑。檔名與環境變數的完整對照見 [SETUP.md Tier 2](SETUP.md#tier-2--api-keys-each-key-unlocks-one-feature-none-required)。

- Pexels / Pixabay（免費）→ 素材庫 B-roll
- Gemini → Veo 生成 B-roll、圖片備援、LLM 字幕斷句、雙語行、強調字幕
- OpenAI → 生圖階梯的最後一階
- Gemini CLI → 五個呼叫點：找產品官網、截圖內容驗證、生成素材的視覺審查、從逐字稿規劃 B-roll、從逐字稿選音樂情緒。這五個沒裝也都有各自的退路

`.env.*` 全部在 gitignore 裡。永遠不要 commit 金鑰。

## Tier 3 — 網站截圖 B-roll

裝 Playwright 與 chromium。腳本提到某個產品或網址時會用到；沒裝的話這一階直接落到素材庫影片。

## 這條線實際上靠什麼在做事

完成一支通過閘門的影片，不需要任何雲端服務。全部跑在你自己的機器上，Tier 2 的金鑰只是替階梯多加幾階選配。

工具與職責的完整對照表在 [SETUP.md — The toolchain](SETUP.md#the-toolchain--what-actually-does-the-work)。一句話版本：剪接、混音、編碼全是 ffmpeg；字幕時間軸是 faster-whisper；膠囊、封面、字卡是 Pillow；音量量測、ducking、閘門算術是 numpy。唯一的大檔下載是 ASR 模型。

## 驗收

```bash
python3 doctor.py                 # 環境檢查，並跑兩套閘門測試
python3 gates.py --preflight      # 印出閘門即將執行的 house style
python3 -m pytest -q              # 全套測試（script 版測試也橋接進來）
```

## Sub-agent 定義

`agents/` 裡有四份 sub-agent 定義：`footage-scout`、`transcript-proofer`、`slide-reader`、`edit-critic`。字幕要引用語音的時候，`transcript-proofer` 是必跑的。在 Claude Code 上把 `agents/*.md` 複製到 `~/.claude/agents/` 就好。

其他 harness 讀不到 frontmatter，但內文就是純指令，換到任何 sub-agent 機制都能重用。完全沒有 sub-agent 機制也沒關係，[AGENTS.md](AGENTS.md) 列出了每一個 agent 的指令替代方案。

## 兩條退路階梯

這兩條階梯存在的理由是同一個：build 不能停下來等人。

B-roll 依素材類型有不同階梯，每一階只需要一樣東西，缺了就往下掉，最後一階是跳過、留在自拍畫面。完整階梯見 [SETUP.md — fallback chains](SETUP.md#the-two-fallback-chains-nothing-here-can-stall-a-build)。

付費那一階（Veo）我故意排在最前面。生成的影片是針對這一段實際在講什麼去配的，素材庫再好也只是主題上接近。Veo 以下全部免費，沒有 Gemini 金鑰時它會自己跳過、整趟只講一次，然後從免費階繼續。沒有付費金鑰跑出來的結果是正常的，我自己大部分時候也是這樣跑。

音樂那條由 `resolve_music.py` 負責，保證會終止，並回報是哪一階答應的：明確路徑 → 專案目錄的 `music/` 投放槽 → `bgm-library/` 的檔名比對 → 情緒相符的替身。走到替身這一階時，交付檔會被改名成 `-standin-<情緒>`，絕不會冒充成你指名的那首歌。口播管線在階梯底下還多一階：連情緒都配不到時，直接用 FFmpeg 合成一段環境 pad。

`bgm-library/` 在公開 repo 裡是空的，音樂授權是每個使用者自己的事，見 [NOTICE.md](NOTICE.md) 與 `bgm-library/README.md`。你丟進 `bgm-library/<情緒>/` 或 `專案目錄/music/` 的任何音檔都會被撿到。

## 檔案配置與可調參數

每個頂層檔案負責什麼、`config.py` 有哪些參數與預設值，都在 [SETUP.md — Layout](SETUP.md#layout--what-each-top-level-file-is) 與 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。這裡不重抄，那是最容易跟程式漂移的一段。

工作檔會落在 `/tmp/video-postprod/<timestamp>/`，交付檔一律落在專案根目錄。

## 疑難排解

| 症狀 | 原因 | 怎麼修 |
|---|---|---|
| `doctor.py` 有 REQUIRED 那列是 ❌ | 缺工具或套件 | 照它印出來的安裝指令做 |
| `ModuleNotFoundError: faster_whisper` | 沒建 venv | 見 Tier 1 |
| 素材庫 B-roll 一直說找不到 API key | skill 根目錄沒有 `.env.pexels` | 見 Tier 2（檔案跟 `SKILL.md` 放在一起，clone 到哪就在哪） |
| 字幕沒有英文行 | 沒有可解析的 Gemini 金鑰 | 見 Tier 2，這一步是設計成乾淨跳過的 |
| Whisper 在 `large-v3` 爆記憶體 | RAM 不夠 | 在 `config.py` 把模型設成 `medium` |
| 輸出的字幕字型不對 | 系統字型覆蓋 | 內建的演示斜黑体才是 house 字型，檢查 `YIIBU_FONT_NAME` |
| 最後編碼跑超過 20 分鐘 | 編碼器選錯，或 filter graph 踩到反模式 | 對 build script 跑 `build_lint.py`，並看 SKILL.md 的「15 分鐘預算」 |
| 閘門 exit 2 | 有決定把工作延後了 | 這不是錯誤，但影片沒有完成，報告會列出還欠哪些 |
