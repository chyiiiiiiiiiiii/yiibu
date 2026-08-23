# 它能放到畫面上的東西

<p align="center"><a href="CAPABILITIES.md">English</a> · 繁體中文</p>

`SKILL.md` 裡有同一份清單的表格版；那是給 agent 讀的純文字介面。這一頁是給人看的，因為人不可能在沒看過長相前，就開口要 `cutout-large`。

**直接抄每張圖卡最後一欄的句子。** 這就是完整介面：你說，agent 去接線。圖上所有數值都在算圖時從 `house_style.json` 或 `config.py` 讀取，所以圖不會宣稱程式沒有使用的幾何。

標示 `render` 的圖卡來自真正的渲染器；標示 `shipped` 的圖卡不是渲染圖，而是實際交付影片的影格，只做裁切。

這一頁不再有任何手畫圖。`render` 圖卡用 `python3 docs/make_gallery.py` 重生；`shipped` 圖卡用 `python3 docs/make_demos.py`。

---

## 字幕

<table>
<tr>
<td width="300"><img src="gallery/captions-two-layer.png" width="290"></td>
<td>

**兩層，各做各的事。** 膠囊在畫面高度 18% 的位置命名這個東西，字幕在 70% 基線解釋它。關鍵字在 76px 白色主行裡用 90px house 金色跳出，英文行放在下方。

> 「幫我加雙語字幕，關鍵字標金色」
> `decisions.json captions:on` · 透過 `house_style.local.json` 開啟雙語

`render` — 膠囊來自 `modules/title.py`，尺寸來自 `house_style.json`

</td>
</tr>
<tr>
<td><img src="gallery/emphasis-captions.png" width="290"></td>
<td>

**把最有力的一句做成主視覺字幕。** 132px，拆成錯落堆疊的短塊，講到哪一塊才進場。它放在人臉偵測回傳的無臉區帶裡，不會壓到臉，而且有回歸測試守住這件事。

> 「最重要那句用大字」
> `SUBTITLE_EMPHASIS_ENABLED` · `EMPHASIS_MAX_MOMENTS` 限制數量

`render`

</td>
</tr>
</table>

## 封面

<table>
<tr>
<td width="300"><img src="gallery/cover.png" width="290"></td>
<td>

**標題最多兩行。** 字級會以字數為代價；多塞第三行只會把字壓到看不見。大字講的是體驗，產品名和平台名放副標；副標會量成和標題同寬，讓整塊在動態牆裡讀起來是一個物件。封面是烙在第 1 幀上的疊圖，不是接在前面的一段影片，否則所有字幕時間都會往後推。

> 「封面寫『潛入 Google 上海辦公室』」
> `modules/cover.py` `build()` · **gated**，閘門會讀 `cover_meta.json`

`render` — 這張圖就是 `cover.build()` 的輸出

</td>
</tr>
</table>

四支實際出貨的封面，橫跨三種題材：

<p align="center"><img src="gallery/covers-real.jpg" width="760"></p>

右邊那兩支是 sizer 存在的理由：同一套模板、標題長度差很多，但副標都被量到和標題同寬，因此仍像一個物件。寬度不再跟著標題時，`gate_cover` 會擋下 build。

## 結尾卡

<table>
<tr>
<td width="300"><img src="gallery/endcard.png" width="290"></td>
<td>

**觀眾看到的最後一幀，而且閘門會檢查影片真的停在它上面。** 先講名字，再一行講是什麼、在哪裡。`gate_structure` 會拿最後一幀比對 `endcard.png`，並用 `endcard_meta.json` 確認卡片宣告了文字；影片淡出過頭跑過結尾卡、根本沒走到它，或交付一張沒有文字的卡，都不會出貨。

> 「結尾放店名跟城市」
> `decisions.json end_card:on` — `off` 必須寫下 why

`shipped` — 這是 `more-joy-young` 實際出貨的結尾卡

</td>
</tr>
</table>

## 前後對照

<p align="center"><img src="gallery/before-after.jpg" width="620"></p>

同一個鏡頭，兩次：手機錄下來的那一幀，和最後出貨的那一幀。構圖、封面標題與副標、house 色盤，兩張圖之間的所有差異都是這個 skill 做的。

## B-roll 版面

四種都是 `BROLL_LAYOUT` 的值。`mixed` 會逐段輪播，同一種不會連續出現超過兩次；這是預設值，因為單一版面撐九十秒看起來就像套版。

下面的畫面來自實際交付影片，不是畫的。每一張對應哪個版面，是把同一段素材送進 `compose.py` 的四個 builder 做對照後確認的，因為目測曾經判錯一次。

<table>
<tr>
<td width="300"><img src="gallery/layout-fullscreen-pip.png" width="290"></td>
<td>

**fullscreen** — 素材鋪滿畫面，你留在帶圈的小圓框裡。這是口播影片的預設值：資訊由 B-roll 承擔，小圓框留一張臉在畫面上，讓它仍讀得出是一個人在講話。

> 「B-roll 全螢幕，我放小圓框」
> `BROLL_LAYOUT="fullscreen"` · `PIP_SIZE` `PIP_POSITION` `PIP_MARGIN_TOP`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-split.png" width="290"></td>
<td>

**split** — 素材在上、你在下，中間一道漸層接縫。素材需要被讀（截圖、規格表）而圓形 PiP 會裁掉內容時，用它。

> 「上下分割，上面放素材」
> `BROLL_LAYOUT="split"` · `SPLIT_RATIO` · `SPLIT_BLUR_HEIGHT`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-background.png" width="290"></td>
<td>

**background** — 素材模糊後沉在置中自拍後面，往下淡出。四種裡最柔的一種：素材是氣氛而不是細節，適合鋪質感，不要拿來放任何人必須讀的東西。

> 「素材當背景就好」
> `BROLL_LAYOUT="background"` · `BG_BROLL_RATIO`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-cutout.png" width="290"></td>
<td>

**cutout，小尺寸** — 你從自己的畫面裡被去背，站在素材前面、左下角。由 MediaPipe 做人物分割。

> 「把我去背站在素材前面」
> `mixed` layout · `cutout.render_cutout_segment` variant `bottom-left-small`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-cutout-large.png" width="290"></td>
<td>

**cutout，大尺寸** — 同一套分割放大到主講人尺寸，站在網站截圖前面。最強也最貴的一種，而且它要求來源畫面光線夠好，遮罩一軟，放大就看得出來。

> 「去背放大，站在網站截圖前面」
> variant `center-large` · geometry via `BLS_*`

`shipped` — 這張頁面上的 contributor 頭像已模糊處理

</td>
</tr>
</table>

---

## 其他效果

這些還沒有圖卡：它們是動態（推進、轉場、ducking）或聲音，用靜態圖呈現會失真。完整效果與觸發方式如下；更完整的 capability map 在 [SKILL.md](../SKILL.md)。

| 效果 | 觸發方式 |
|---|---|
| 靜態圖 Ken Burns | 圖片 B-roll 自動套用 · `BROLL_KENBURNS_ZOOM` |
| 影片 punch-in | `buildkit.punch_in` |
| 進出場轉場 | `BROLL_TRANSITION_TYPES` · fade / zoom_in / slide_left / slide_up |
| fit-with-blur | 高於 9:16 的素材保留全貌，兩側模糊 |
| 頂部標題橫幅 | `--top-title` · `--top-title-mode` |
| 開場字卡 | `--title` · `--card-subtitle` |
| CTA 疊圖 | `--cta-image` |
| 拍手刪除重來 | 拍一次手；靜音步驟會刪掉前 3 秒 |
| 靜音修剪 | speech-band RMS profiling |
| 音樂床與 duck | `--music "<你說的話>"` · **gated** |
| 選擇性保留原音 | `decisions.json audio_policy: selective` · `audio_policy.json` · **gated** |
| 轉場音效 | `--sfx` |
| 響度 | `decisions.json loudness` |
