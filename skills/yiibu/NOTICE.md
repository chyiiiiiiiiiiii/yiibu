# Third-party assets

The MIT licence in `LICENSE` covers the **code** in this repository. Media is
handled separately, and the repo's rule is simple: **no audio is redistributed
here at all.**

| path | what | status |
|---|---|---|
| `assets/fonts/演示斜黑体.otf` | the bundled CJK caption font — a slanted Source Han Sans derivative by Keynoteart, released under **SIL OFL 1.1** (publisher announcement and independent record linked in `assets/fonts/OFL.txt`, verified 2026-08-18) | Bundled because it IS the house style — `house_style.json` names it and the Typography gate enforces it. OFL permits bundling and redistribution; the required licence text ships beside the font. One caveat is documented in `OFL.txt`: the derivative's internal name retains the base font's reserved word "Source" — an upstream naming choice, noted for transparency. `YIIBU_FONT_NAME` swaps in any installed font. |
| `assets/fonts/NotoSansTC-Black.otf` | an upright alternative caption font — Noto Sans TC Black (Source Han Sans TC Heavy), from `notofonts/noto-cjk`, **SIL OFL 1.1** (source and licence in `assets/fonts/OFL-NotoSansTC.txt`, verified 2026-10-21) | Bundled as an option, not the default: the upright heavy face of the 黑底白字 look common on 抖音／小紅書, for food and street-interview edits where the slanted house font reads too fast. A project opts in with `YIIBU_FONT_FILE` pointing at it plus `{"font": {"family": "Noto Sans TC"}}` in `WORK_DIR/house_style.local.json`, so the Typography gate checks the font actually used. |
| `assets/fonts/GenSenRounded2TW-H.otf` | the Spotlight (重點) caption face — 源泉圓體 TW Heavy (GenSenRounded2 TW H), a rounded Source Han Sans derivative by ButTaiwan, release v2.100 of `ButTaiwan/gensen-font`, **SIL OFL 1.1** (source and licence in `assets/fonts/OFL-GenSenRounded.txt`, verified 2026-10-23) | Bundled as an accent, not a caption font: `house_style.json` `captions.spotlight` names it and only the `Spotlight` style may use it. `title._find_font()` skips it, so it can never become the face a whole video falls back to. |
| `bgm-library/` | music beds | **Ships empty.** Free stock licences (e.g. Mixkit) permit using a track in your video, not redistributing the file — so each user downloads their own. See `bgm-library/README.md`. |
| `sfx-library/` | transition whoosh | Same — ships empty, drop in your own. |
| `docs/demo/*.gif`, `docs/banner*.png` | demo renders and banner | Made from the author's own footage for this repo. Three further demos are held back and `docs/make_demos.py` lists each with its reason — a bystander child in frame, third-party official footage, and one the author excluded. |
| `docs/gallery/covers-real.jpg`, `before-after.jpg`, `endcard.png` | shipped artifacts | The author's own footage and their own team, published by the author already. |
| `docs/gallery/layout-*.png` | B-roll layout examples | Frames from the author's own published videos. Two carry material the author did not shoot: `layout-fullscreen-pip.png` shows a stock or generated clip that includes a person, and `layout-cutout-large.png` shows the public GitHub page of `browser-use/browser-harness` (MIT) with the contributor avatars blurred. Both appear as incidental B-roll inside a screenshot of this project's output, not as redistributed assets, and the author reviewed and cleared them for publication. |
| `docs/gallery/gates-blocked.{png,txt}` | a real blocked gate run | The author's own project; the seeded defects and the capture are described in the `.txt` header. |

Anything downloaded per-project (commercial songs, official B-roll) is excluded
by `.gitignore` and must never be committed. The music ladder in
`resolve_music.py` is deliberately built so that a commercially released song
can only enter a build by the user supplying a file they are licensed to use.
