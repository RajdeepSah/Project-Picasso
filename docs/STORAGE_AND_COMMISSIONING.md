# Phase 4 storage and SD workflow

Phase 4 software is implemented. Physical-card copy/readback and machine commissioning have **not** been performed. The software never starts a drawing or opens a serial port.

## Launch and try without hardware

Install once with `python3 scripts/setup.py`, then launch with `python3 scripts/picasso.py`. After source updates, rebuild with `python3 scripts/setup.py --skip-install`. Existing locked dependencies cover this phase; no new runtime packages were added.

1. Enter **Draw a beautiful mandala**, inspect the path, and adjust its dimensions/placement.
2. Open **Saved history** to search, reopen or inspect earlier revisions. Completed revisions save automatically; browser reload and service restart retain them.
3. Choose **Test export without hardware**, then **Prepare simulation job**.
4. Choose **Create test directory**. This selects only the app-owned `data/test-card` directory.
5. Review replacement and choose **Export to test directory**. Success requires final `main.nc` readback matching the frozen job SHA-256; it is labeled **Test copy verified**.
6. Optionally opt into automatically copying this exact frozen job when this selected target is accessible. This can copy immediately. Turn it off when finished.

Simulation jobs cannot update physical cards or the local `SdCard/main.nc`. A test-directory result is evidence of software behavior, not a physical-card, firmware or motion check. Creating a new drawing does not change the prepared job or automatic-sync selection.

## Import a drawing

Use **Import drawing** to choose a local `.nc`, `.gcode`, `.txt` or Picasso `.json` file. Files are read by the browser and sent as bounded text; paths are never accepted as server write destinations. Imports create new saved drafts without overwriting the source. SVG import is deferred; SVG export remains supported.

Choose the dialect deliberately:

- **Picasso strict:** the exported restricted dialect, parsed and checked before normalization.
- **Absolute-mm linear:** G0/G00 and G1/G01 with modal XY; first XY move must establish both axes with a motion mode. G17, G21 and G90 are accepted; standalone M2/M30 end the program. Balanced parenthesis and semicolon comments are stripped. An exact known vendor banner is allowed only before commands. Z≤0 means pen down; Z>0 means pen up. G0 does not lift the pen implicitly. Positive F values are accepted but ignored, with a visible note. Arcs, inches, relative modes, offsets, spindle commands, unknown words, duplicate axes and commands after program end are rejected.
- **Picasso JSON:** validates a complete draft, exact G-code checksum and geometry/preview roundtrip, then creates a fresh imported draft. Imported metadata cannot mark it execution-ready or restore a physical preparation.

Original bounds and source SHA-256 are retained. With **Center drawing at (0,0) explicitly** unchecked and no fit, original drawing placement is preserved. Centering/fitting happens only when requested. The supplied `mandala_11x14.gcode` has 252 mm occupied width; the browser test explicitly centers and fits it to 120 mm. The drawing preview shows the canonical output path and actual dimensions before preparation.

Pen-down strokes are retained. Source pen-up detours are replaced with direct canonical travel between strokes and from the assumed start, so this importer does not promise verbatim travel equivalence. New travel is previewed and must pass preparation constraints. Unsupported dwell/timing/laser/3D semantics must not be treated as pen plotting.

G-code input is ASCII, at most 1 MB and 20,000 lines; JSON input is at most 8 MB of text. Generated output retains the engine's 20,000-point, 1,000-stroke, 1 MB G-code and 250 m total-path budgets. Imported drawings support size, rotation and placement; seed/detail/regeneration controls do not invent replacement source geometry.

## Record the actual machine

The project was rechecked in this phase:

- Actual directory spelling is `SdCard/`; it is a local source collection, not a mounted card.
- Root `WallDrawingMachine.ino` is empty.
- `Drawbot_C/02 arduino code/Walldraw/Walldraw.ino` uses 350 mm motor spacing.
- `SdCard/02 arduino code/Walldraw/Walldraw.ino` uses 400 mm spacing.

These references cannot establish which firmware/calibration is installed. Bundled source values are labeled reference defaults and remain unverified. The application does not choose between them automatically.

Open **Machine → Record / edit measurements**. Record the actual board, measured spacing/anchor height/spool/steps/pen angles, approved rectangle with margins, minimum/maximum rope lengths, observer, notes and repeatable manual-origin procedure. Workspace/rope fields require operator input. Record the installed-firmware match, tested pen lift/holding and tested workspace explicitly before selecting verified status. Saving/selecting an unverified profile remains useful but cannot unlock physical preparation.

A verified Phase 4 profile must match the chosen source reference's firmware-dependent values exactly. Measurements that differ can be saved unverified; reconcile firmware in Phase 5 before verifying. Verification means **operator-recorded evidence**; it is not telemetry or automatic hardware certification. No synthetic test profile is installed in the user's data directory.

Edits create a new profile version/hash and retain prior versions. Existing prepared jobs are never silently updated. Export requires the job's profile to remain current, verified and selected; changing its calibration invalidates the preparation. Changing selected profile blocks export until the intended current profile is selected and the job is reviewed/prepared again.

## Prepare and export to a physical card

1. Record and select the actual verified measured profile. Inspect the drawing at its final size and center placement.
2. Choose **Prepare for drawing**, then **Prepare physical job**. The immutable job freezes revision, code/hash, preview, profile snapshot and expected `(0,0)` start. All rounded drawing and travel endpoints must lie inside the measured rectangle/margins below the anchors. Rope checks include each segment's interior nearest point, endpoint maximum length and half-step allowance.
3. Connect a card reader and mount the card with the host OS. Refresh targets and explicitly select the intended card. Linux discovery inspects removable/USB ancestry with `lsblk`; writes require a mounted writable FAT16/FAT32 filesystem (`vfat`/`msdos`) and stable UUID. Non-FAT or UUID-less candidates are unavailable for writes. No disk is mounted, formatted or selected automatically.
4. Review current `main.nc`, acknowledge its backup/replacement, exclusive computer ownership and the manual origin/start procedure. Optionally choose to update the local `SdCard/main.nc` mirror from the same job. **Stage local SD mirror only** works without a mounted card, for a physically prepared job.
5. Export. Publication verifies the selected volume/root identity, reviewed existing hash, free space and current job/profile; backs up old `main.nc`; writes short FAT-compatible temporary files; flushes/closes and verifies the staged code; activates managed `main.nc` and `PICASSO.JSN`; then reads back the final code before reporting success.
6. Close file handles and use the OS's **safe eject**. Move the card to the Arduino, establish the recorded physical **and firmware** `(0,0)` state, and start manually using its SD menu. Repeat the origin procedure **before every job**, including a second drawing whose predecessor ended elsewhere. The app cannot observe/reset the stock firmware's coordinates. If this cannot be established, do not execute the job; finish Phase 5 commissioning first.

UUID/path and mounted instance checks prevent accidental substitution; symlink roots/ancestors/files are rejected. Replaced `main.nc` backups are retained in `data/backups/`; the original local mirror's first backup is recorded separately. Only `main.nc` and the app-owned `PICASSO.JSN` manifest are managed. Other files/subdirectories are not mirrored, deleted or renamed. If using a preexisting unrelated `PICASSO.JSN`, preserve it manually before adopting that reserved name.

Local mirror and card publication are separately journaled operations. If mirror staging succeeds and card export fails, the mirror can already contain the prepared job; inspect transfer records. A post-activation readback failure may leave the new file on the destination but is always reported failed. Review the target and backup before retrying; never interpret failure as proof that nothing changed. File flush/rename/readback cannot guarantee power-loss atomicity on actual removable media.

Physical discovery currently supports Linux; verified publication uses POSIX directory descriptors and locks. macOS/Windows physical export is not verified/implemented. The app has no eject button and cannot guarantee the Arduino/computer are electrically isolated; exclusive card ownership is an explicit operator condition.

## Automatic synchronization

Automatic sync is off by default and applies to **one frozen job and one explicitly selected volume/path**, with the reviewed previous hash and ownership/start acknowledgements. It can run immediately and on reinsertion while the app is running. It persists across app restarts when left enabled. It never selects the latest drawing or starts motors.

A two-second watcher waits when the selected card is absent. A profile revision/selection mismatch, external edit, identity mismatch or nontransient write/checksum failure pauses automatic export for review. Reinsertion of the same approved target triggers a new verified publication; a changed path/volume requires explicit selection. Selecting a new target disables automatic sync. Configuration/selection and copy operations share an export lock; a concurrent change reports busy and must be retried after the active operation finishes. An already active copy is not cancellable by closing the dialog.

Turn off sync before intentionally editing a managed file or changing card ownership. The user remains responsible for safe eject and physical start. Transfer records distinguish copying, verified, failed and interrupted operations; test-directory and physical-card records are separate kinds.

## Backups and recovery

Default app data is `data/` (ignored by Git):

```text
data/
  picasso.sqlite3             # schema version 1; metadata/settings/profiles/journal/recovery copies
  artifacts/<opaque-id>/     # draft.json, drawing.nc, preview.svg OR job.json + drawing.nc
  .staging/                  # transient immutable-save staging
  recovery/                  # uncommitted and before-repair directories preserved for inspection
  backups/<target-hash>/     # verified previous main.nc copies
  test-card/                 # opt-in isolated test destination
  export.lock                # cross-process configuration/publication lock
```

History retains all saved revisions; no automatic deletion/quota migration is implemented. Each read checks the immutable artifact hashes. Missing/damaged entries show **Repair** in history: repair verifies the database's compressed exact copy against its manifest, preserves the damaged directory in recovery, then restores bytes. If database/recovery data itself is damaged, restore your external backup. Repair does not reconstruct measured calibration evidence.

Startup quarantines uncommitted/staging directories and marks unfinished copying records **interrupted**. It never reports them as a successful save/export. Inspect any interrupted target before explicit retry. Recovery notices describe the current startup scan; the preserved recovery directories remain available afterward.

For backup, stop Picasso and copy the **entire `data/` directory**, including any SQLite WAL/SHM files still present, to safe storage. Also preserve any intentional source/mirror changes separately. Restore while the app is stopped, using the same app version or a compatible migration. A newer unsupported schema causes startup to fail instead of rewriting the database. No destructive reset or recursive card sync is exposed by the API.

For tests or a separate local installation, backend environment overrides `PICASSO_DATA_DIR` and `PICASSO_MIRROR_DIR` select administrator-controlled paths. They are not request parameters. Automated API/browser tests always use temporary data and mirror directories, preserving original assets.

## Hardware acceptance still pending

No physical removable card was available during implementation. Before calling the full physical workflow verified, record the card UUID/filesystem/mount, export/read back a small physically prepared file, safely eject/reinsert and check it on the board. Record the actual board/core/installed sketch, measured calibration, origin repeatability, pen settling/holding, rope tension and drawing dimensions. Phase 5 hardens the firmware and completes those commissioning checks. Phase 6 adds acknowledged USB control; existing USB currently offers neither mass-storage access nor a drawing-upload protocol. A separate card reader works now; eliminating card shuffling requires firmware/protocol work or additional hardware/connectivity.
