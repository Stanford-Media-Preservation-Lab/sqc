# Installation — Ubuntu 24.04 LTS

`sqc` is cross-platform (like `vdg`), unlike `srw` which is Ubuntu-only.

## 1. Update package index

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 2. Install FFmpeg, MediaConch, MediaInfo, and ExifTool

Ubuntu's default repos carry older MediaConch/MediaInfo versions. Install the
current releases from the MediaArea repository:

```bash
wget https://mediaarea.net/repo/deb/repo-mediaarea_1.0-27_all.deb
sudo dpkg -i repo-mediaarea_1.0-27_all.deb
sudo apt update
sudo apt install -y ffmpeg mediaconch mediainfo libimage-exiftool-perl
```

> If the `.deb` filename above 404s, MediaArea has published a newer repo
> package — check [mediaarea.net/en/Repos](https://mediaarea.net/en/Repos)
> for the current version and substitute it above.

MediaTrace has no standalone binary — it's provided by `mediaconch --Mediatrace`.

Verify:

```bash
ffmpeg -version
mediaconch --version
mediainfo --version
exiftool -ver
```

---

## 3. Install Python 3.11+

Ubuntu 24.04 ships Python 3.12. Verify:

```bash
python3 --version
```

`sqc` needs Python 3.11+ for stdlib `tomllib` (used to read policy profiles —
no third-party TOML dependency).

---

## 4. Install pipx (if not already present)

```bash
sudo apt install -y pipx
pipx ensurepath
```

Open a new shell (or `source ~/.bashrc`) afterward so pipx's bin directory is
on `PATH`.

---

## 5. Install sqc

```bash
pipx install git+https://github.com/michaelangeletti/sqc.git
```

pipx installs the console script into an isolated environment, matching this
lab's other tools (`cta`, `srw`, `vdg`). Pushing a commit to the repo does
**not** automatically update an already-installed copy — after any update:

```bash
pipx reinstall sqc
```

### Development install (contributing to sqc itself)

```bash
git clone https://github.com/michaelangeletti/sqc.git
cd sqc
pip3 install -e .
```

---

## 6. Verify installation

```bash
sqc --help
sqc --version
```

---

## 7. Set up policy profiles (vendor-qc only)

`sqc vendor-qc` looks for profiles in `--profiles-dir` (default `./profiles`)
and their referenced MediaConch policy XML in `--mediaconch-dir` (default
`./MediaConch`). The bundled `profiles/v210_quad_ntsc.toml` and
`MediaConch/v210_quad_ntsc.xml` ship with the repo; add new profiles for
other vendor formats (1" Type C, outsourced 1/2" EIAJ) as `.toml`/`.xml`
pairs — see [MANUAL.md](MANUAL.md#policy-profile-format).

`sqc donor-triage` doesn't need any of this — it has no policy profile.

---

## Running tests

```bash
pip3 install pytest
pytest
```

Tests mock all external tool subprocess calls — no real `ffmpeg`/`mediainfo`/
`mediaconch`/`exiftool` invocation happens in the test suite. Validate actual
tool integration by running `sqc` against a real or synthetic file.
