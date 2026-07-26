"""Turns a ScanResult into something a person can read."""

from __future__ import annotations

import html
import json
import os
from dataclasses import asdict

from .scanner import ERROR, INFO, WARNING, ScanResult

_LABEL = {ERROR: "BROKEN", WARNING: "WARNING", INFO: "note"}
_COLOR = {ERROR: "\033[31m", WARNING: "\033[33m", INFO: "\033[36m"}
_RESET = "\033[0m"


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def to_text(result: ScanResult, *, color: bool = True, show_info: bool = False) -> str:
    lines: list[str] = []
    issues = [
        i for i in result.sorted_issues() if show_info or i.severity != INFO
    ]

    for issue in issues:
        rel = os.path.relpath(issue.path, result.root)
        label = _LABEL[issue.severity]
        if color:
            label = f"{_COLOR[issue.severity]}{label}{_RESET}"
        lines.append(f"[{label}] {rel}")
        lines.append(f"    {issue.message}")
        for other in issue.related:
            lines.append(f"    also: {os.path.relpath(other, result.root)}")
        if issue.fix:
            lines.append(f"    fix: {issue.fix}")
        lines.append("")

    lines.append(
        f"Scanned {result.package_count} packages, {result.script_count} script mods, "
        f"{result.other_count} other files ({_human_size(result.total_bytes)})."
    )
    n_err, n_warn, n_info = len(result.errors), len(result.warnings), len(result.infos)
    if n_err == 0 and n_warn == 0:
        lines.append("Nothing broken found.")
    else:
        lines.append(
            f"{n_err} broken, {n_warn} worth a look, "
            f"{n_info} note{'s' if n_info != 1 else ''}."
        )
        if not show_info and n_info:
            lines.append("Re-run with --all to see the notes.")
    return "\n".join(lines)


def to_json(result: ScanResult) -> str:
    payload = {
        "root": result.root,
        "summary": {
            "packages": result.package_count,
            "scripts": result.script_count,
            "other_files": result.other_count,
            "total_bytes": result.total_bytes,
            "errors": len(result.errors),
            "warnings": len(result.warnings),
            "infos": len(result.infos),
        },
        "issues": [asdict(i) for i in result.sorted_issues()],
    }
    return json.dumps(payload, indent=2)


def to_html(result: ScanResult) -> str:
    rows: list[str] = []
    for issue in result.sorted_issues():
        rel = html.escape(os.path.relpath(issue.path, result.root))
        related = "".join(
            f"<div class='rel'>also: {html.escape(os.path.relpath(p, result.root))}</div>"
            for p in issue.related
        )
        fix = f"<div class='fix'>{html.escape(issue.fix)}</div>" if issue.fix else ""
        rows.append(
            f"<li class='{issue.severity}'>"
            f"<span class='tag'>{_LABEL[issue.severity]}</span>"
            f"<div class='body'><div class='path'>{rel}</div>"
            f"<div class='msg'>{html.escape(issue.message)}</div>{related}{fix}</div></li>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sims 4 mod check</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0 auto; padding: 2rem 1rem;
         max-width: 60rem; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .sub {{ opacity: .7; margin-bottom: 1.5rem; word-break: break-all; }}
  .counts span {{ display: inline-block; margin-right: 1rem; font-weight: 600; }}
  ul {{ list-style: none; padding: 0; margin: 1.5rem 0 0; }}
  li {{ display: flex; gap: .75rem; padding: .75rem; border-radius: .5rem;
        margin-bottom: .5rem; background: rgba(127,127,127,.10); }}
  .tag {{ flex: 0 0 5.5rem; font-size: .72rem; font-weight: 700; letter-spacing: .04em;
          text-transform: uppercase; padding-top: .15rem; }}
  .body {{ min-width: 0; }}
  .path {{ font-family: ui-monospace, monospace; word-break: break-all; }}
  .msg {{ opacity: .85; }}
  .rel {{ font-family: ui-monospace, monospace; font-size: .85em; opacity: .7;
          word-break: break-all; }}
  .fix {{ font-size: .9em; opacity: .75; margin-top: .25rem; }}
  .error .tag {{ color: #c0392b; }}
  .warning .tag {{ color: #b7791f; }}
  .info .tag {{ color: #2b6cb0; }}
</style></head><body>
<h1>Sims 4 mod check</h1>
<div class="sub">{html.escape(result.root)}</div>
<div class="counts">
  <span>{len(result.errors)} broken</span>
  <span>{len(result.warnings)} warnings</span>
  <span>{len(result.infos)} notes</span>
  <span>{result.package_count} packages &middot; {result.script_count} scripts
        &middot; {_human_size(result.total_bytes)}</span>
</div>
<ul>{"".join(rows) or "<li class='info'><span class='tag'>OK</span>"
              "<div class='body'>Nothing to report.</div></li>"}</ul>
</body></html>
"""
