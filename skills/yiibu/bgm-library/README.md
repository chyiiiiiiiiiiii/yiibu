# bgm-library — bring your own tracks

This folder ships **empty** (audio is gitignored) because music licensing is
per-user: most "free" stock licences — Mixkit's included — let you use a track
*in your video* but not redistribute the audio file itself, which is exactly
what committing it to a public repo would do.

Filling it takes two minutes and unlocks the whole music path:

```
bgm-library/
  chill/        ← lofi, calm         (the default mood)
  energetic/    ← upbeat, hype
  inspiring/    ← uplifting, epic
  dramatic/     ← tense, cinematic
```

1. Download tracks you are licensed to use — e.g. [mixkit.co/free-stock-music](https://mixkit.co/free-stock-music/)
   (free, no attribution) or your own library.
2. Drop each file (`.mp3` / `.m4a` / `.wav`) into the mood folder that fits.
   Filenames matter: `resolve_music.py` rung 3 matches the user's requested
   track name against them.
3. Done — no config change. `config.py _default_bgm()` picks the first track
   in the default-mood folder; `resolve_music.py` uses the folders as the
   mood-matched stand-in pool.

An empty library still never stalls a build: the music step resolves to
"no music" and says so, and the no-music deliverable ships regardless.

`sfx-library/whoosh.mp3` (the transition sound) is the same story: drop in any
short whoosh you are licensed to use, or the SFX step skips cleanly.
