# Firmware commissioning guide

Follow this guide after uploading the canonical firmware (`firmware/README.md`) and before trusting any drawing. Every step is a physical observation; the app records your results but cannot observe them. Keep the pen raised and the moves small until a step says otherwise. Stop by pressing **ESC**. If anything moves unexpectedly, switch off the motor supply.

Record each result in the machine profile's measurement notes, together with the date, the observer and the firmware configuration ID. A profile is **verified** only when every check below has passed on this machine and the dialog's attestations are true.

## 0. Prerequisites

- The board is identified from its markings, processor and USB bridge, and the exact FQBN that uploaded successfully is recorded. A compiled UNO reference build alone is not identification.
- The motor supply voltage and rating, the common ground, and the ULN2003 wiring against the pin table in `firmware/README.md` have been inspected. The motors are never powered from MCU pins.
- Motor separation, anchor height above the intended origin mark and spool diameter have been measured, and the reachable paper area and rope limits estimated conservatively. These values are saved as an **unverified** profile with *Picasso canonical firmware* selected.
- `machine_config.h` was generated from that saved profile, then built and uploaded. The *Info* screen shows the same configuration ID as the studio dialog. If it does not, stop: the flashed values differ.

## 1. Boot and origin state

1. Power-cycle the board with the pen at a random position. Expected: the boot screen, then `Origin: unset`. `SD job → ENTER` on a valid card reaches `Set origin 1st` and does not move.
2. Note whether opening the USB serial port resets the board: the boot line reappears. This matters for Phase 6.

## 2. Pen servo and settling (pen up throughout motion)

1. *Setup → Pen test*: toggle a few times. Measure the time the pen needs to fully clear the paper and to fully land, for example with a phone slow-motion video.
2. If either time exceeds `PICASSO_PEN_UP_SETTLE_MS` or `PICASSO_PEN_DOWN_SETTLE_MS` (300 ms) in `picasso_config.h`, raise the setting and rebuild. If the 85°/70° angles do not clear or contact correctly, adjust them in the profile and regenerate the configuration. That changes the ID, so read it again.

## 3. Rope direction and jog signs

1. *Setup → Jog ropes*, then *L rope +*, ENTER: the **left rope must lengthen**, lowering that side. Run *L rope −* and check that it shortens. Repeat with *R rope ±*.
2. If a rope moves the opposite way, the direction constants or the winding differ from the reference machine. Stop and do not draw. Correct `PICASSO_M*_LENGTHEN/SHORTEN` in `picasso_config.h`, document the change, rebuild, and repeat this step. Drawings would otherwise be mirrored or would run outside the workspace.
3. Each jog is 64 steps, about 3.4 mm of rope at the nominal 35 mm spool. Measure one jog with a ruler against the rope to check the spool diameter.

## 4. Physical origin and tension

1. Use jogs to bring the pen to the marked origin with both ropes taut. Then run *Setup → Set origin* and confirm. The main menu shows `Origin: ready`.
2. Repeatability: *Test square* (next step), then *Go to origin*, which ends `Origin: moved`. Measure the distance between the pen and the mark, and repeat three times.

## 5. Dimensions and orientation

1. With the pen able to draw, run *Setup → Test square* (needs a fresh origin). Measure all four sides, which should be 20 mm, and both diagonals, which should be 28.28 mm. Check that +X is to your right and +Y is up toward the anchor line.
2. Prepare a small circle of about 40 mm in the studio against this profile, export it to the card, insert the card, and run *SD job*. The `CRC` shown must equal the studio's *machine check* value. Measure the horizontal and vertical diameters.
3. Systematic distortion points to wrong spacing, anchor height or spool values. Correct the profile, regenerate the configuration, rebuild, and repeat the checks from step 2.

## 6. Holding, drift and thermal behaviour

1. After a completed job, the coils stay energized by default. Leave the machine for 10 minutes, then check for gondola drift and touch-check the motor and driver temperature.
2. *Release motors*: note whether the gondola slips. The origin becomes unset, as intended.
3. Record the decision. Keep `PICASSO_RELEASE_AFTER_JOB 0` unless the measurements justify releasing the coils.

## 7. SD error handling

Run each case with the pen raised or with blank paper:

| Case | Expected screen | Motion |
| --- | --- | --- |
| No card inserted | `FAILED / SD init failed` | none |
| Card without `main.nc` | `FAILED / No main.nc` | none |
| A raw vendor sample copied as `main.nc` | `FAILED / LINE_LONG` or `MISSING_Z`, with the line number | none |
| A studio job edited to include `G2 X0 Y0 Z0` at the end | `FAILED / UNSUP_G`, with the line number | none |
| A coordinate outside the workspace | `FAILED / OUT_REGION` | none |
| Card pulled during a drawing | `FAILED / SD read error`, pen raised, coils held | stops |

## 8. Pause and stop response

1. During a drawing, press ENTER. Expected: `PAUSED pen up`. ENTER again resumes; the pen lowers and drawing continues on the same line.
2. Press ESC during a long pen-down segment. Use a slow-motion video to measure from key press to the end of motion and to the pen clearing the paper. Host simulation predicts about 25–30 ms to the last step and the raise command, mostly keypad debounce, plus the servo's own travel. **Record the measured value.** The simulation is not this measurement.
3. After a stop, *SD job* must refuse to start (`Set origin 1st`) until the origin is confirmed again.

## 9. D10 and SPI interaction

Run *SD job* validation several times with the coils energized: after a completed job, hold the motors. Watch the left motor during card initialisation. Note any twitch or audible step, then run *Go to origin* and confirm that the pen returns to the mark. Record the result. Do not reassign pins unless an observed problem requires it, and document any change.

## 10. USB protocol checks (firmware 0.6.0+)

Run these with the pen raised first, then with a small drawing:

1. Select the board's port in **Machine → USB machine** and connect. The handshake must report the same configuration ID as the *Info* screen, and the boot ID must match the `@BOOT` frame. Record whether connecting reset the board: a new boot ID and `Origin: unset`.
2. Set the origin on the keypad, prepare a small square and start it over USB. Every acknowledged command should match visible motion. Compare the final commanded position with the pen on the paper.
3. Press **Pause** in the studio: the pen rises and settles. **Resume** continues the same line. Then press **Stop** during a long pen-down segment and measure, with slow-motion video, the time from the click to the pen clearing. Repeat with ESC on the keypad.
4. Pull the USB cable during a pen-down segment. The firmware must raise the pen and abort within about 3 s (`HOST_LOST`). The studio must show a fault or lost connection and must not resume after you reconnect.
5. Start an SD job validation on the keypad, then try a USB start. The firmware must refuse (`MACHINE_BUSY`/`STATE`).

Record the measured latencies and any reset-on-connect behaviour in the profile notes.

## 11. Verify the profile

When steps 1–9 pass:

1. Edit the profile: enter the configuration ID from *Info*.
2. Tick the firmware, pen/holding and workspace attestations, then *Mark this profile verified*.
3. Save. The studio refuses a mismatched ID.
4. Prepare physical jobs only against this verified revision. Any later change to a compiled value requires a rebuild and repeating the affected checks.
