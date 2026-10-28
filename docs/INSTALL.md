# Install / update

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

## WorkBuddy

Paste the repository URL into WorkBuddy together with a request to install the
SAYFRAME skill. The host needs to inspect `SKILL.md` and copy only the verified
manifest-listed files into its skill directory. Start a new conversation after
installation. Repository import behavior depends on the WorkBuddy version.

If that route is unavailable, download the versioned skill ZIP from Releases and
use WorkBuddy's **Add skill → Upload skill** flow. The root `SKILL.md` and scripts
are the same in the ZIP and source repository.

## Local source installation

```powershell
git clone https://github.com/msaysay/sayframe.git
cd sayframe-workbuddy
python scripts/install.py
```

This installs into `~/.workbuddy/skills/sayframe-workbuddy`, verifies manifest
hashes, preserves the private runtime and backs up existing recognized skill code.
It does not copy your cloned Git history, recordings or arbitrary extra files.
Finish active editing jobs before updating. It does not kill WorkBuddy processes.

## First use

Ask for framework and direction suggestions first. Python 3.11/3.12 is required.
The host runs `scripts/sayframe.py doctor`; only if dependencies are missing should
it explain and run `scripts/setup.py`. Downloads include pinned Python packages,
FFmpeg and a SenseVoice alignment model. Full runtime requirements and upstream
links are in `references/student-guide.md` and `THIRD_PARTY_NOTICES.md`.

`AudioTranscribe` is preferred when the current WorkBuddy session exposes it;
local recognition remains available if it does not. Native cloud tools follow
the provider's data handling and account limits. Local rendering does not imply
that WorkBuddy's reasoning or transcription is offline/free.

The first video import creates a draft, not an approved edit. Confirm a direction,
then choose captions on/off and title on/off. The tool will not encode a newly
imported project until those choices are present.

## Recovery

Keep original recordings where the project can still find them. Use the same
project path for follow-up edits. Do not manually rewrite project JSON or timestamps.
Undo/redo restores verified old renders when available. Failed exports preserve
the source and diagnostics. If you relocate the raw recording, re-import it into
a new project rather than changing source hashes by hand.

Fresh-machine setup, URL installation and marketplace ingestion must be checked
in your target WorkBuddy version; earlier local tests are not certification of
every distribution route.
