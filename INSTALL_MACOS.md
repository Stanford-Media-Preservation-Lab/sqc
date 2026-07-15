# Installation — macOS (Apple Silicon)

## 1. Install Homebrew

If not already installed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

## 2. Install FFmpeg, MediaInfo, MediaConch, and ExifTool

```bash
brew install ffmpeg mediainfo mediaconch exiftool
```

MediaTrace has no standalone binary — it's provided by `mediaconch --Mediatrace`,
so no separate install is needed for it.

Verify:

```bash
ffmpeg -version
ffprobe -version
mediainfo --version
mediaconch --version
exiftool -ver
```

---

## 3. Install Python 3.11+

```bash
brew install python@3.12
```

`sqc` needs Python 3.11+ for stdlib `tomllib` (used to read policy profiles —
no third-party TOML dependency).

---

## 4. Install pipx (if not already present)

```bash
brew install pipx
pipx ensurepath
```

Open a new shell afterward so pipx's bin directory is on `PATH`.

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

## Running tests

```bash
pip3 install pytest
pytest
```

Tests mock all external tool subprocess calls — no real `ffmpeg`/`mediainfo`/
`mediaconch`/`exiftool` invocation happens in the test suite. Validate actual
tool integration by running `sqc` against a real or synthetic file.
