# What this can put on screen

<p align="center">English · <a href="CAPABILITIES.zh-TW.md">繁體中文</a></p>

SKILL.md carries the same list as a table, and that is the right form for an
agent: it reads SKILL.md as text and cannot see a picture. This page is for the
person, who cannot ask for `cutout-large` without knowing what one looks like.

**Copy the phrase in the last column.** That is the whole interface — you say it,
the agent wires it. Every value quoted on a tile is read from `house_style.json`
or `config.py` at render time, so a tile cannot claim geometry the code does not
use.

`render` tiles come out of the real renderer. `shipped` tiles are not renders
at all — they are frames from a video that actually went out, cropped and
nothing else.

Nothing on this page is drawn any more. Regenerate with
`python3 docs/make_gallery.py` for the `render` tiles and
`python3 docs/make_demos.py` for the `shipped` ones.

---

## Captions

<table>
<tr>
<td width="300"><img src="gallery/captions-two-layer.png" width="290"></td>
<td>

**Two layers, and they do different jobs.** The pill NAMES the thing at 18% of
frame height; the caption EXPLAINS it on the 70% baseline. Keywords pop in house
gold at 90px inside the 76px white line, and the English line sits under it.

> 「幫我加雙語字幕，關鍵字標金色」
> `decisions.json captions:on` · bilingual via `house_style.local.json`

`render` — pill from `modules/title.py`, sizes from `house_style.json`

</td>
</tr>
<tr>
<td><img src="gallery/emphasis-captions.png" width="290"></td>
<td>

**Hero captions for the one line that lands.** 132px, split into stacked chunks
at staggered positions, each entering as it is spoken. Placed inside the
face-free band that face detection returns — it never lands on a face, and there
is a regression test asserting that.

> 「最重要那句用大字」
> `SUBTITLE_EMPHASIS_ENABLED` · `EMPHASIS_MAX_MOMENTS` caps how many

`render`

</td>
</tr>
</table>

## Cover

<table>
<tr>
<td width="300"><img src="gallery/cover.png" width="290"></td>
<td>

**At most two title lines — the sizer trades point size for character count, so
a third line shrinks the type to nothing.** The big line says the *experience*;
product and platform names go in the subtitle, which is sized to match the
title's width so the block reads as one object in a feed. Burned as an overlay
on frame 1, never prepended as a segment (that would shift every caption).

> 「封面寫『潛入 Google 上海辦公室』」
> `modules/cover.py` `build()` · **gated**, and the gate reads `cover_meta.json`

`render` — this tile IS `cover.build()` output

</td>
</tr>
</table>

Four covers that actually shipped, across three genres:

<p align="center"><img src="gallery/covers-real.jpg" width="760"></p>

The two on the right are the sizer's whole argument. Same template, wildly
different title lengths — and in both, the subtitle is measured to match the
title's width, so the block reads as one object instead of two stacked
decisions. `gate_cover` fails the build when that width stops tracking.

## End card

<table>
<tr>
<td width="300"><img src="gallery/endcard.png" width="290"></td>
<td>

**The last frame the viewer sees, and the gate checks the video actually ends
on it.** Name, then the one-line what-and-where. `gate_structure` compares the
final frame against `endcard.png`, and checks `endcard_meta.json` declares the
text on it — a video that fades past its own end card, never reaches it, or
ships a card that says nothing does not ship.

> 「結尾放店名跟城市」
> `decisions.json end_card:on` — `off` needs a written why

`shipped` — this is `more-joy-young`'s actual end card

</td>
</tr>
</table>

## Before and after

<p align="center"><img src="gallery/before-after.jpg" width="620"></p>

One shot, twice: the frame the phone recorded, and the frame that shipped.
Framing, cover title and subtitle, and the house palette — everything between
those two pictures is what the skill did.

## B-roll layouts

All four are `BROLL_LAYOUT` values. `mixed` rotates between them per segment and
never repeats one more than twice in a row, which is the default because a
single layout held for ninety seconds reads as a template.

These are frames from videos that actually shipped, not drawings. Which layout
each one is was confirmed against a controlled render — the same clip pushed
through `compose.py`'s four builders — because eyeballing them got it wrong once.

<table>
<tr>
<td width="300"><img src="gallery/layout-fullscreen-pip.png" width="290"></td>
<td>

**fullscreen** — the asset fills the frame, you stay in a ringed circle.
The default for talking-head videos: the B-roll carries the information, the PiP
keeps a face on screen so it still reads as a person talking.

> 「B-roll 全螢幕，我放小圓框」
> `BROLL_LAYOUT="fullscreen"` · `PIP_SIZE` `PIP_POSITION` `PIP_MARGIN_TOP`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-split.png" width="290"></td>
<td>

**split** — asset on top, you below, with a gradient seam between them.
Use it when the asset needs to be read (a screenshot, a spec table) and a
circular PiP would crop it.

> 「上下分割，上面放素材」
> `BROLL_LAYOUT="split"` · `SPLIT_RATIO` · `SPLIT_BLUR_HEIGHT`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-background.png" width="290"></td>
<td>

**background** — the asset sits blurred behind a centred selfie, fading out
partway down. The softest of the four: the asset sets a mood rather than
carrying detail, so use it for texture, not for anything anyone has to read.

> 「素材當背景就好」
> `BROLL_LAYOUT="background"` · `BG_BROLL_RATIO`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-cutout.png" width="290"></td>
<td>

**cutout, small** — you are segmented out of your own footage and stand IN
FRONT of the asset, bottom-left. MediaPipe does the segmentation.

> 「把我去背站在素材前面」
> `mixed` layout · `cutout.render_cutout_segment` variant `bottom-left-small`

`shipped`

</td>
</tr>
<tr>
<td><img src="gallery/layout-cutout-large.png" width="290"></td>
<td>

**cutout, large** — the same segmentation at presenter scale, in front of a
website screenshot. The strongest of the set and the most expensive; it also
wants a well-lit source, because a soft mask shows at this size.

> 「去背放大，站在網站截圖前面」
> variant `center-large` · geometry via `BLS_*`

`shipped` — the contributor avatars on that page are blurred

</td>
</tr>
</table>

---

## Everything else

These have no tile yet — they are motion (a push-in, a transition, a duck) or
audio, and a still frame would misrepresent them. The full list with triggers is
the capability map in [SKILL.md](../SKILL.md).

| effect | trigger |
|---|---|
| Ken Burns on stills | automatic for image B-roll · `BROLL_KENBURNS_ZOOM` |
| punch-in on video | `buildkit.punch_in` |
| entry/exit transitions | `BROLL_TRANSITION_TYPES` · fade / zoom_in / slide_left / slide_up |
| fit-with-blur | taller-than-9:16 assets kept whole, blurred sides |
| top-title banner | `--top-title` · `--top-title-mode` |
| title card | `--title` · `--card-subtitle` |
| CTA overlay | `--cta-image` |
| clap-mistake removal | clap once; the silence step deletes the 3s before it |
| silence trim | speech-band RMS profiling |
| music bed + duck | `--music "<what you said>"` · **gated** |
| selective original audio | `decisions.json audio_policy: selective` · `audio_policy.json` · **gated** |
| transition SFX | `--sfx` |
| loudness | `decisions.json loudness` |
