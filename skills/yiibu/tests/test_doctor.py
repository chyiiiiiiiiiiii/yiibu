"""doctor.py said "ready" to an ffmpeg that cannot burn a single caption.

Homebrew's `ffmpeg` formula no longer links libass (checked 2026-09-26: 9.0.x,
dependency list has no libass and no freetype; `ffmpeg-full` has both). An
ffmpeg built that way has no `ass` and no `subtitles` filter, and those two are
the only way a caption reaches the picture: `modules/compose.py` burns with
`ass=`, `buildkit.burn_subtitles` with `subtitles=`.

The macOS CI leg installed exactly what doctor.py told a Mac user to install,
doctor printed "ready", and the first real burn died inside the filtergraph
parser. The parser error does not say "no such filter" — with the filter
missing it has no shorthand to bind a bare path to, so it reports
`No option name near '/path/s.ass'`, which reads like a quoting bug. Three
weekly runs were read that way. The check belongs where "ready" is decided.
"""
import os
import pathlib
import stat
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "modules")]

import doctor  # noqa: E402

# The head and a few rows of a real `ffmpeg -hide_banner -filters` (7.1.1).
FILTERS_HEAD = """Filters:
  T.. = Timeline support
  .S. = Slice threading
  ..C = Command support
  A = Audio input/output
  V = Video input/output
  N = Dynamic number and/or type of input/output
  | = Source or sink filter
 TSC overlay           VV->V      Overlay a video source on top of the input.
 ..C scale             V->V       Scale the input video size and/or convert the image format.
"""
LIBASS_ROWS = """\
 ... ass               V->V       Render ASS subtitles onto input video using the libass library.
 ... subtitles         V->V       Render text subtitles onto input video using the libass library.
"""


def _fake_ffmpeg(tmp_path, monkeypatch, listing):
    (tmp_path / "filters.txt").write_text(listing)
    exe = tmp_path / "ffmpeg"
    exe.write_text(f"#!/bin/sh\ncat '{tmp_path / 'filters.txt'}'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(doctor, "problems", [])


def test_an_ffmpeg_without_libass_is_not_ready(tmp_path, monkeypatch, capsys):
    """Reconstructs the defect: Homebrew's plain ffmpeg, on a Mac."""
    _fake_ffmpeg(tmp_path, monkeypatch, FILTERS_HEAD)
    monkeypatch.setattr(sys, "platform", "darwin")

    doctor.need_libass()

    out = capsys.readouterr().out
    assert doctor.problems == ["libass"], out
    assert "ffmpeg-full" in out, (
        "the fix on a Mac is ffmpeg-full; `brew install ffmpeg` is what "
        f"produced this ffmpeg in the first place:\n{out}")


def test_an_ffmpeg_with_libass_is_ready(tmp_path, monkeypatch, capsys):
    _fake_ffmpeg(tmp_path, monkeypatch, FILTERS_HEAD + LIBASS_ROWS)

    doctor.need_libass()

    assert doctor.problems == [], capsys.readouterr().out
