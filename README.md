# sims4modcheck

Point it at your Sims 4 Mods folder and it tells you which mods are broken,
which ones the game silently ignores, and which ones fight each other.

No dependencies, nothing to install, and it never modifies your mods unless you
explicitly ask it to.

## Use it

```bash
python3 -m sims4modcheck "~/Documents/Electronic Arts/The Sims 4/Mods"
```

Just want to know what's broken, nothing else? That's the fast path — it reads
only the header of each mod, so it finishes quickly even on a huge folder:

```bash
python3 -m sims4modcheck "~/Documents/Electronic Arts/The Sims 4/Mods" --quick
```

On Windows:

```
python -m sims4modcheck "%USERPROFILE%\Documents\Electronic Arts\The Sims 4\Mods"
```

Sample output:

```
[BROKEN] wcif.ts4script
    Built for Python 3.3 (1 file), but the game runs Python 3.7. It will not load.
    fix: Look for an updated version of this mod.

[BROKEN] newmod.zip
    An archive sitting in Mods. The game cannot read inside archives, so nothing in it is loaded.
    fix: Extract it and put the .package / .ts4script files in Mods, then delete the archive.

[WARNING] overrideA.package
    Overrides the same 1 resource as 1 other mod. Only one of them wins in game,
    and which one is not predictable.
    also: overrideB.package

Scanned 9 packages, 2 script mods, 3 other files (1.4 KB).
6 broken, 4 worth a look, 1 note.
```

Exit code is `1` if anything is broken, `0` if not, `2` if the folder does not exist.

## What it checks

**Packages (.package)**

- Empty or truncated files — a failed download that looks fine in Explorer.
- Files that aren't packages at all, e.g. an HTML error page saved as `.package`.
- Sims 2 / Sims 3 packages, which The Sims 4 loads but ignores.
- Corrupt resource indexes.
- Files buried more than 5 folders deep, which the game never reads.
- **Conflicts**: two mods overriding the same game resources. Only one wins,
  and which one is not predictable.

**Script mods (.ts4script)**

- Archives that aren't valid zips, or fail their CRC check.
- Bytecode built for the wrong Python version — the game runs 3.7, and this is
  the single most common reason a script mod does nothing at all.
- Source-only releases with no compiled `.pyc`.
- Scripts more than one folder deep, which the game never loads.

**Everything else**

- Unextracted `.zip` / `.rar` / `.7z` archives sitting in Mods.
- Unfinished downloads (`.crdownload`, `.part`) and disabled mods (`.disabled`).
- Byte-identical duplicates of the same mod installed in two places.
- Readmes and preview images, listed as notes only.

## Options

| Option | What it does |
| --- | --- |
| `--all` | Also show informational notes (readmes, unknown file types). |
| `--html FILE` | Write a browsable HTML report. |
| `--json FILE` | Write full results as JSON (`-` for stdout). |
| `--remove` | Take the broken mods out of Mods. They go to a `Broken Mods` folder alongside it — moved, never deleted. Asks first. |
| `--quarantine DIR` | Same as `--remove`, but you choose the destination. |
| `--yes` | Skip the quarantine confirmation. |
| `--no-conflicts` | Skip conflict detection — much faster on very large folders. |
| `--no-duplicates` | Skip duplicate detection. |
| `--max-conflicts N` | How many conflicting groups to report (default 50). |
| `--max-tracked-resources N` | Memory ceiling for conflict detection (default 3,000,000, about 275 MB). |
| `--timeout SECONDS` | Give up on any single file after this long and carry on (default 60; 0 waits forever). |
| `--quiet` | No progress output. |

Don't want a report, just want the broken mods gone:

```bash
python3 -m sims4modcheck ~/path/to/Mods --quick --remove
```

It lists what it found, asks once, then moves those files into a `Broken Mods`
folder next to your Mods folder. The game stops loading them immediately, and
nothing is deleted — drag anything back if you disagree with a call.

Mods that are merely in the wrong place are never moved; those need relocating
within Mods, not removing.

## Notes and limits

- Conflict detection compares resource keys. Two mods overriding the same
  resource is normal and often intentional (a default replacement, a merged
  package) — it's a "check this if something looks wrong", not an error.
- The tool cannot tell whether a mod is out of date for the current game patch.
  Nothing in the file records which patch it was built for; only the creator's
  download page knows.
- Package contents are never decompressed, so scanning a large Mods folder is
  quick.
- Conflict detection is the only part of the scan whose memory grows with your
  folder size — it remembers every resource key it has seen, at about 92 bytes
  each. It stops tracking at 3 million resources and says so in the report
  rather than exhausting RAM. `--no-conflicts` skips it entirely.
- The scan has two phases: walking the files, then hashing same-sized files to
  find duplicates. Both report progress, so a still counter means real work,
  not a hang.
- If one file takes more than 5 seconds the tool says so on screen, and after
  `--timeout` seconds it abandons that file and carries on, listing it in the
  report. A healthy local file reads instantly, so a slow one usually means the
  file is still in iCloud rather than on disk, lives on a drive that has gone to
  sleep, or is damaged.

## Development

```bash
python3 -m pytest
```

The tests build real DBPF and `.ts4script` bytes rather than mocking, so the
parsers are exercised end to end.
