# Canvas-Syncer

Sync files from the Files tab of your [Canvas](https://canvas.stanford.edu) courses into a local directory.

## Install

```bash
pip install -e .
# or
pip install -r requirements.txt && pip install -e .
```

Run as an installed command or as a module:

```bash
canvassyncer
python -m canvassyncer
```

## Setup

1. In Canvas, open **Account → Settings → New Access Token** and create a token.
2. Store it in the OS keyring (preferred) or set `CANVAS_API_TOKEN`:

```bash
canvassyncer login
# or
export CANVAS_API_TOKEN='your-token'
```

3. Create a config file (created automatically on first run, or with `-r`):

```bash
canvassyncer -r
```

Default config path: `~/.config/canvassyncer/config.json`

```json
{
  "canvas_url": "https://canvas.stanford.edu",
  "download_dir": "~/Courses",
  "max_file_size_mb": 250,
  "courses": {
    "12345": "CS224N",
    "67890": "EE101"
  }
}
```

- `courses` maps a **numeric course ID** (from the Canvas URL, e.g. `https://canvas.stanford.edu/courses/12345`) to a local folder name under `download_dir`.
- Absolute folder paths are used as that course’s root.
- The access token is **never** stored in this file. Use `canvassyncer login` / `logout`, or `CANVAS_API_TOKEN`.

## Usage

```bash
canvassyncer              # sync all configured courses
canvassyncer -y           # accept prompts (skip oversized files, update newer versions)
canvassyncer -p ./cfg.json
canvassyncer -x http://proxy:8080
canvassyncer -d           # debug output
canvassyncer login
canvassyncer logout
canvassyncer -V
```

On each run the tool:

1. Lists folders and files for each course via the Canvas REST API.
2. Downloads files that are missing locally.
3. When Canvas has a newer version, optionally archives the local file as `<mtime>_<filename>` and downloads the update.
4. Leaves an empty placeholder for files larger than `max_file_size_mb` unless you choose to download them.

## Token resolution

1. Environment variable `CANVAS_API_TOKEN`
2. OS keyring service `canvassyncer`, account = Canvas host (e.g. `canvas.stanford.edu`)

## Development

```bash
pip install -e ".[dev]"
pytest
```
