---
name: geektime-cli
description: Use the geektime CLI to query GeekTime courses and articles, download content the user can access, and export downloaded courses to Markdown or PDF. Use for requests about the user's 极客时间 library; not for unrelated web research.
---

# GeekTime CLI

Use the `geektime` command for the user's own 极客时间 library. This skill supplies command guidance; it does not provide an account, course content, or credentials.

## Prepare

1. Check `geektime --version`. If the command is absent, install the published package with `uv tool install geektime-cli` when installing tools is appropriate in the current environment. It needs Python 3.10+ and Google Chrome. See the repository README for video and PDF system dependencies.
2. Check `geektime login --check` before account queries or downloads. If login is needed, run `geektime login` and let the user complete the browser login. Never request, print, or copy passwords, cookies, or session files.
3. Use `geektime <command> --help` when options are unclear; do not invent course IDs, names, or flags.

## Query

- List purchased courses with `geektime course list --json`. Use `--scope all` only when the user wants the whole catalog. Filter with `--type c1,c3,p,d,q` when useful.
- Get IDs from the returned list before running `geektime course info <id> --json`, `geektime course chapters <id> --json`, or `geektime article detail <id> --json`.
- Prefer normalized `--json` for structured answers. `--json` and `--raw` cannot be combined. Summarize relevant results instead of echoing a full private library or article when the user asked a narrow question.

## Download and export

- `geektime download` downloads all purchased courses by default. Match the user's requested scope; for a small initial sample use `geektime download --limit 3 --text-only`. Add `--type c1` or `--output-dir <directory>` when needed. Video downloads require `ffmpeg`.
- Preserve the download directory for exports. Both download and export use `./GeekTime` by default. To see local course names, run `geektime export markdown --download-dir <directory>` without `--course`.
- Export one downloaded course with `geektime export markdown --course "<exact course name>" --download-dir <directory>` or replace `markdown` with `pdf`. Omit `--download-dir` when using the default directory. PDF export requires WeasyPrint system libraries.
- Confirm that expected files were created before reporting a completed download or export. If login expires, return to the browser login flow. If no local course matches, list available course names rather than guessing.

Only retrieve or download content the user is entitled to access, and follow the service's terms. Keep account data and downloaded content out of repository commits and shared responses unless the user explicitly asks to share them.
