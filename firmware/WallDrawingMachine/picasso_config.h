// Hardware configuration preserved from the reference Walldraw.ino sketches.
// Calibration (spacing, anchors, spool, pen angles, workspace) lives in the
// generated machine_config.h instead; see firmware/README.md.
#ifndef PICASSO_CONFIG_H
#define PICASSO_CONFIG_H

#define PICASSO_FIRMWARE_VERSION "0.6.0"
#define PICASSO_DIALECT "picasso-fw-v1"
#define PICASSO_PROTOCOL_VERSION 1

// Pin map: unchanged from the reference sketches (UNO-style wiring comments).
#define PICASSO_LEFT_IN1 7
#define PICASSO_LEFT_IN2 8
#define PICASSO_LEFT_IN3 9
#define PICASSO_LEFT_IN4 10   // also hardware SS on ATmega328P; kept as OUTPUT
#define PICASSO_RIGHT_IN1 2
#define PICASSO_RIGHT_IN2 3
#define PICASSO_RIGHT_IN3 5
#define PICASSO_RIGHT_IN4 6
#define PICASSO_SERVO_PIN A0
#define PICASSO_KEYPAD_PIN A1
#define PICASSO_BEEP_PIN A2
#define PICASSO_SD_CS_PIN 4
#define PICASSO_BAUD 115200

// USB protocol: a host-started job stops if no valid frame arrives for this long.
#define PICASSO_HOST_TIMEOUT_MS 3000
// EEPROM address of the 32-bit boot counter that forms the boot ID.
#define PICASSO_EEPROM_BOOT_ADDRESS 0

// Direction constants: legacy values. The legacy names M1_REEL_IN/M2_REEL_IN
// are the directions moveto() uses when IK asks for a longer rope, so they
// are named by that kinematic effect here. Verify with the pen-up jog check.
#define PICASSO_M1_LENGTHEN 1     // legacy M1_REEL_IN
#define PICASSO_M1_SHORTEN (-1)   // legacy M1_REEL_OUT
#define PICASSO_M2_LENGTHEN (-1)  // legacy M2_REEL_IN
#define PICASSO_M2_SHORTEN 1      // legacy M2_REEL_OUT

// TinyStepper settings: legacy values. Each single-step move starts a new
// ramp, so the effective period is 1e6 / sqrt(2 * acceleration) ~= 2236 us
// per motor step, exactly as in the legacy blocking moveto().
#define PICASSO_STEPPER_SPEED 10000
#define PICASSO_STEPPER_ACCELERATION 100000

// Resistor-ladder keypad: legacy nominal ADC values and +/-10 window.
#define PICASSO_KEY_DOWN_ADC 330
#define PICASSO_KEY_ENTER_ADC 90
#define PICASSO_KEY_ESC_ADC 517
#define PICASSO_KEY_WINDOW 10
#define PICASSO_KEY_IDLE_ADC 1020
// New: debounce by requiring identical samples taken at a fixed interval.
#define PICASSO_KEY_SAMPLE_MS 10
#define PICASSO_KEY_STABLE_SAMPLES 3

// Pen settling. Down keeps the legacy TPD delay; up previously had none.
// Both are starting points: bench-measure clearance and record the result.
#define PICASSO_PEN_DOWN_SETTLE_MS 300
#define PICASSO_PEN_UP_SETTLE_MS 300

// Commissioning moves.
#define PICASSO_JOG_STEPS 64          // ~3.4 mm of rope at the nominal 35 mm spool
#define PICASSO_TEST_SQUARE_MM 20.0f  // square centred on the origin

// Completion signal. Independent of coil holding (legacy beep() released both
// motors before checking BEEP_SW).
#define PICASSO_BEEP_ENABLED 1

// Coil policy. 0 (default): coils stay energized after every job so the
// gondola cannot drift; only the explicit Release action de-energizes them.
// 1: release after each job and invalidate the origin.
#define PICASSO_RELEASE_AFTER_JOB 0

// SD bytes processed per loop() pass, bounding keypad service latency.
#define PICASSO_READ_BYTES_PER_LOOP 32

#endif
