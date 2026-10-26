// Project Picasso canonical firmware for the existing wall drawing machine.
//
// Derived from the reference Drawbot_C/SdCard Walldraw.ino sketches with the
// same pin map, libraries, kinematics and step sequencing. The blocking loop
// is replaced by cooperative state machines: keypad, pen settling, SD reading
// and motion are serviced on every loop() pass, so pause/stop are honoured
// between bounded motion slices. SD jobs are validated completely (syntax,
// workspace and rope limits) before any motion. A host can stream a job over
// USB with serial protocol v1 (docs/SERIAL_PROTOCOL.md): one acknowledged
// command at a time, never executed twice. See firmware/README.md.

#include <TinyStepper_28BYJ_48.h>
#include <Servo.h>
#include <SD.h>
#include <U8x8lib.h>
#include <EEPROM.h>
#include <string.h>

#include "picasso_config.h"
#include "picasso_core.h"

#if defined(PICASSO_MACHINE_CONFIG)
#include PICASSO_MACHINE_CONFIG
#elif __has_include("machine_config.h")
#include "machine_config.h"
#else
#error "machine_config.h is missing. Generate it from a profile: python3 scripts/firmware.py config --profile <id> (see firmware/README.md)."
#endif

static_assert(PICASSO_PROTOCOL_VERSION == 1, "sendHello() and docs/SERIAL_PROTOCOL.md describe protocol version 1");
static_assert(PICASSO_CONFIG_SCHEMA == 1, "machine_config.h targets a different configuration schema; regenerate it");
static_assert(PICASSO_PEN_UP_DEGREES >= 0 && PICASSO_PEN_UP_DEGREES <= 180, "pen up angle out of range");
static_assert(PICASSO_PEN_DOWN_DEGREES >= 0 && PICASSO_PEN_DOWN_DEGREES <= 180, "pen down angle out of range");
#if PICASSO_HAS_REGION
static_assert(PICASSO_REGION_MAX_Y_MM < PICASSO_ANCHOR_Y_MM, "workspace must lie below the anchor line");
static_assert(PICASSO_REGION_MIN_X_MM + PICASSO_REGION_MARGIN_MM <= 0 && PICASSO_REGION_MAX_X_MM - PICASSO_REGION_MARGIN_MM >= 0 &&
              PICASSO_REGION_MIN_Y_MM + PICASSO_REGION_MARGIN_MM <= 0 && PICASSO_REGION_MAX_Y_MM - PICASSO_REGION_MARGIN_MM >= 0,
              "the origin (0,0) must lie inside the margin-adjusted workspace");
#endif

U8X8_SSD1306_128X64_NONAME_HW_I2C u8x8(/* reset=*/ U8X8_PIN_NONE);
TinyStepper_28BYJ_48 m1;  // left motor
TinyStepper_28BYJ_48 m2;  // right motor
Servo pen;
File jobFile;

static picasso::Geometry geometry;

// All types precede the first function: the Arduino builder inserts
// generated prototypes there.
enum Key : uint8_t { KEY_NONE, KEY_DOWN, KEY_ENTER, KEY_ESC };
enum Mode : uint8_t {
  MODE_MAIN, MODE_SETUP, MODE_INFO, MODE_CONFIRM, MODE_JOG, MODE_PEN_TEST,
  MODE_MESSAGE, MODE_VALIDATING, MODE_READY, MODE_EXECUTING, MODE_RESULT
};
enum Phase : uint8_t { EX_FETCH, EX_SETTLE, EX_MOVE, EX_PAUSING, EX_PAUSED, EX_RESUMING, EX_ENDING };
enum JobKind : uint8_t { JOB_SD, JOB_SQUARE, JOB_ORIGIN, JOB_USB };
enum Outcome : uint8_t { OUTCOME_COMPLETED, OUTCOME_ABORTED, OUTCOME_FAILED };
enum Reason : uint8_t {
  REASON_NONE, REASON_PARSE, REASON_STOPPED, REASON_SD_INIT, REASON_NO_FILE, REASON_SD_READ,
  REASON_FILE_CHANGED, REASON_NO_MOVES, REASON_HOST_STOP, REASON_HOST_LOST, REASON_SEQUENCE
};
enum Confirm : uint8_t { CONFIRM_ORIGIN, CONFIRM_RELEASE };
enum MotionResult : uint8_t { MOTION_BUSY, MOTION_DONE, MOTION_HELD };
enum Fetch : uint8_t { FETCH_BUSY, FETCH_COMMAND, FETCH_END, FETCH_FAILED };

static const char kReasons[][16] PROGMEM = {
  "", "", "Stopped by user", "SD init failed", "No main.nc", "SD read error", "File changed", "No moves",
  "Host stop", "Host lost", "Sequence error",
};
// Protocol reason codes, in Reason order (REASON_PARSE uses the status code).
static const char kReasonCodes[][13] PROGMEM = {
  "NONE", "PARSE", "STOPPED", "SD_INIT", "NO_FILE", "SD_READ", "FILE_CHANGED", "NO_MOVES",
  "HOST_STOP", "HOST_LOST", "SEQUENCE",
};
static const char kJogLabels[4][11] PROGMEM = {"L rope +", "L rope -", "R rope +", "R rope -"};

// ---------------------------------------------------------- position model
// The origin is valid only after the operator confirms the pen is at the
// physical origin. Reset never creates one. A job additionally needs a fresh
// confirmation: any motion consumes it.
static bool originValid = false;
static bool originFresh = false;
static float posX = 0, posY = 0;
static long rope1 = 0, rope2 = 0;  // commanded rope lengths in steps
static uint16_t originRevision = 0;  // increments on every confirmed origin

// ------------------------------------------------------------ host session
// Boot ID: EEPROM counter incremented on every reset, so a host can tell a
// reset (and therefore an unknown position) from a continuing session.
static uint32_t bootId = 0;
static picasso::FrameReader frames;
static bool hostJob = false;          // job started by the host: watchdog applies
static unsigned long hostSeenAt = 0;  // last valid frame
static char usbToken[9];
static uint32_t usbReceived = 0, usbCompleted = 0;
static bool usbPending = false;       // received and validated, not yet started
static bool usbInFlight = false;      // started, not yet acknowledged
static picasso::Command usbCommand;
static uint16_t txCrc = 0;

// --------------------------------------------------------------------- pen
static bool penDown = false;
static unsigned long penChangedAt = 0;
static unsigned int penSettleMs = 0;

static void commandPen(bool down) {
  if (down == penDown) return;
  penDown = down;
  pen.write(down ? PICASSO_PEN_DOWN_DEGREES : PICASSO_PEN_UP_DEGREES);
  penChangedAt = millis();
  penSettleMs = down ? PICASSO_PEN_DOWN_SETTLE_MS : PICASSO_PEN_UP_SETTLE_MS;
}

static bool penSettled() { return millis() - penChangedAt >= penSettleMs; }

// ------------------------------------------------------------------ keypad
static Key keyCandidate = KEY_NONE, keyStable = KEY_NONE;
static uint8_t keyCount = 0;
static unsigned long keySampledAt = 0;

static Key classifyKey(int value) {
  if (value >= PICASSO_KEY_IDLE_ADC) return KEY_NONE;
  if (value > PICASSO_KEY_DOWN_ADC - PICASSO_KEY_WINDOW && value < PICASSO_KEY_DOWN_ADC + PICASSO_KEY_WINDOW) return KEY_DOWN;
  if (value > PICASSO_KEY_ENTER_ADC - PICASSO_KEY_WINDOW && value < PICASSO_KEY_ENTER_ADC + PICASSO_KEY_WINDOW) return KEY_ENTER;
  if (value > PICASSO_KEY_ESC_ADC - PICASSO_KEY_WINDOW && value < PICASSO_KEY_ESC_ADC + PICASSO_KEY_WINDOW) return KEY_ESC;
  return KEY_NONE;
}

// Returns a key once per debounced press; never blocks while a key is held.
static Key pollKey() {
  unsigned long now = millis();
  if (now - keySampledAt < PICASSO_KEY_SAMPLE_MS) return KEY_NONE;
  keySampledAt = now;
  Key sample = classifyKey(analogRead(PICASSO_KEYPAD_PIN));
  if (sample != keyCandidate) {
    keyCandidate = sample;
    keyCount = 0;
  }
  if (keyCount < PICASSO_KEY_STABLE_SAMPLES) ++keyCount;
  if (keyCount < PICASSO_KEY_STABLE_SAMPLES || keyStable == keyCandidate) return KEY_NONE;
  keyStable = keyCandidate;
  return keyStable;
}

// ------------------------------------------------------------------ buzzer
static uint8_t beepToggles = 0;
static bool beepHigh = false;
static unsigned int beepOnMs = 0, beepOffMs = 0;
static unsigned long beepAt = 0;

static void startBeep(uint8_t count, unsigned int onMs, unsigned int offMs) {
  if (!PICASSO_BEEP_ENABLED || count == 0) return;
  beepOnMs = onMs;
  beepOffMs = offMs;
  beepHigh = true;
  beepAt = millis();
  beepToggles = static_cast<uint8_t>(count * 2 - 1);
  digitalWrite(PICASSO_BEEP_PIN, HIGH);
}

static void serviceBeep() {
  if (!beepToggles || millis() - beepAt < (beepHigh ? beepOnMs : beepOffMs)) return;
  beepHigh = !beepHigh;
  digitalWrite(PICASSO_BEEP_PIN, beepHigh ? HIGH : LOW);
  beepAt = millis();
  --beepToggles;
}

// ----------------------------------------------------------------- display
// Four double-height rows of 16 characters. Text is copied from flash so
// screen strings do not occupy SRAM.
static char screen[4][17];

static void clearText() { memset(screen, 0, sizeof(screen)); }

static void textP(uint8_t row, PGM_P text) {
  strncpy_P(screen[row], text, 16);
  screen[row][16] = '\0';
}

static void textRam(uint8_t row, const char* text) {
  strncpy(screen[row], text, 16);
  screen[row][16] = '\0';
}

static void appendRam(uint8_t row, const char* text) {
  size_t used = strlen(screen[row]);
  if (used < 16) strncat(screen[row], text, 16 - used);
}

static void appendP(uint8_t row, PGM_P text) {
  size_t used = strlen(screen[row]);
  if (used < 16) strncat_P(screen[row], text, 16 - used);
}

static void render() {
  u8x8.clear();
  for (uint8_t row = 0; row < 4; ++row) {
    if (screen[row][0]) u8x8.draw1x2String(0, row * 2, screen[row]);
  }
}

static void formatUnsigned(char* out, uint32_t value) {
  char digits[11];
  uint8_t count = 0;
  do {
    digits[count++] = static_cast<char>('0' + value % 10);
    value /= 10;
  } while (value);
  while (count) *out++ = digits[--count];
  *out = '\0';
}

static void formatHex(char* out, uint32_t value) {
  for (int8_t shift = 28; shift >= 0; shift -= 4) {
    uint8_t nibble = (value >> shift) & 0xF;
    *out++ = static_cast<char>(nibble < 10 ? '0' + nibble : 'a' + nibble - 10);
  }
  *out = '\0';
}

static void originText(uint8_t row) {
  if (!originValid) textP(row, PSTR("Origin: unset"));
  else if (originFresh) textP(row, PSTR("Origin: ready"));
  else textP(row, PSTR("Origin: moved"));
}

// ----------------------------------------------------------- state machine
static Mode mode = MODE_MAIN;
static Mode messageReturn = MODE_MAIN;
static uint8_t cursor = 0;
static Confirm confirming = CONFIRM_ORIGIN;

static const uint8_t kMainItems = 3;
static const uint8_t kSetupItems = 6;

// Job state shared by SD jobs and built-in programs.
static JobKind jobKind = JOB_SD;
static Phase phase = EX_FETCH;
static Phase pausedFrom = EX_FETCH;
static bool pauseRequested = false, stopRequested = false, resumePenDown = false;
static Reason stopReason = REASON_STOPPED;
static bool hasResult = false;
static Outcome outcome = OUTCOME_COMPLETED;
static Reason reason = REASON_NONE;
static picasso::Status failure = picasso::OK;
static bool motionStarted = false;
static uint32_t failedLine = 0;

static picasso::LineReader reader;
static picasso::JobChecker checker;
static picasso::Command current;
static uint32_t fileSize = 0, bytesRead = 0, crc = picasso::kCrcInitial;
static uint32_t validatedCrc = 0, validatedLines = 0, validatedMoves = 0;

static picasso::Command program[8];
static uint8_t programLength = 0, programIndex = 0;

// Motion: legacy line_safe() sub-targets and moveto() step interleave,
// executed one TinyStepper single-step move at a time.
static picasso::LinePlanner planner;
static picasso::StepIterator steps;
static TinyStepper_28BYJ_48* activeMotor = 0;
static bool motorBusy = false, subTargetActive = false;
static float subX = 0, subY = 0;
static long subRope1 = 0, subRope2 = 0;

// Jog: single-motor rope steps while the origin is invalid.
static int8_t jogDirection = 0;
static uint16_t jogRemaining = 0;

static void logEvent(const __FlashStringHelper* event) {
  Serial.print(F("PICASSO "));
  Serial.println(event);
}

static void setOrigin() {
  posX = 0;
  posY = 0;
  picasso::ik(geometry, 0, 0, rope1, rope2);
  originValid = true;
  originFresh = true;
  ++originRevision;
  logEvent(F("ORIGIN SET"));
}

static void invalidateOrigin() {
  originValid = false;
  originFresh = false;
}

// ------------------------------------------------------- protocol frames out
// Frames are written directly to Serial while the CRC is accumulated, so no
// transmit buffer is needed.
static void txByte(char ch) {
  txCrc = picasso::crc16Update(txCrc, static_cast<uint8_t>(ch));
  Serial.write(static_cast<uint8_t>(ch));
}

static void txP(PGM_P text) {
  char ch;
  while ((ch = static_cast<char>(pgm_read_byte(text++)))) txByte(ch);
}

static void txRam(const char* text) {
  while (*text) txByte(*text++);
}

static void txBegin(PGM_P kind) {
  Serial.write('@');
  txCrc = picasso::kCrc16Initial;
  txP(kind);
}

static void txWordP(PGM_P text) {
  txByte(' ');
  txP(text);
}

static void txWord(const char* text) {
  txByte(' ');
  txRam(text);
}

static void txNumber(uint32_t value) {
  char text[11];
  formatUnsigned(text, value);
  txWord(text);
}

static void txHex(uint32_t value) {
  char text[9];
  formatHex(text, value);
  txWord(text);
}

// Commanded millimetres with three decimals.
static void txFixed(float value) {
  long scaled = static_cast<long>(value * 1000.0f + (value >= 0 ? 0.5f : -0.5f));
  txByte(' ');
  if (scaled < 0) {
    txByte('-');
    scaled = -scaled;
  }
  char text[11];
  formatUnsigned(text, static_cast<uint32_t>(scaled / 1000));
  txRam(text);
  txByte('.');
  uint16_t fraction = static_cast<uint16_t>(scaled % 1000);
  txByte(static_cast<char>('0' + fraction / 100));
  txByte(static_cast<char>('0' + fraction / 10 % 10));
  txByte(static_cast<char>('0' + fraction % 10));
}

static void txEnd() {
  char hex[5];
  uint16_t value = txCrc;
  for (int8_t i = 3; i >= 0; --i) {
    uint8_t nibble = value & 0xF;
    hex[i] = static_cast<char>(nibble < 10 ? '0' + nibble : 'A' + nibble - 10);
    value >>= 4;
  }
  hex[4] = '\0';
  Serial.write('*');
  Serial.print(hex);
  Serial.write('\n');
}

static void reasonCode(char* code, size_t size) {
  if (reason == REASON_PARSE) picasso::statusCode(failure, code, size);
  else {
    strncpy_P(code, kReasonCodes[reason], size - 1);
    code[size - 1] = '\0';
  }
}

static void txJobKind() {
  if (jobKind == JOB_USB) {
    txWordP(PSTR("USB:"));
    txRam(usbToken);
  } else txWordP(jobKind == JOB_SD ? PSTR("SD") : jobKind == JOB_SQUARE ? PSTR("SQUARE") : PSTR("HOME"));
}

static void txJob() {
  if (mode == MODE_EXECUTING) txJobKind();
  else txWordP(PSTR("-"));
}

static bool deviceIdle() { return mode == MODE_MAIN || mode == MODE_RESULT; }

static PGM_P protocolState() {
  if (deviceIdle()) return PSTR("IDLE");
  if (mode != MODE_EXECUTING) return PSTR("LOCAL");
  switch (phase) {
    case EX_PAUSING: return PSTR("PAUSING");
    case EX_PAUSED: return PSTR("PAUSED");
    case EX_RESUMING: return PSTR("RESUMING");
    case EX_ENDING: return PSTR("ENDING");
    default: return PSTR("RUNNING");
  }
}

static void sendStatus() {
  txBegin(PSTR("ST"));
  txWordP(protocolState());
  txJob();
  txHex(bootId);
  txNumber(originRevision);
  txWordP(!originValid ? PSTR("UNSET") : originFresh ? PSTR("FRESH") : PSTR("VALID"));
  txFixed(posX);
  txFixed(posY);
  txWordP(penDown ? PSTR("DOWN") : PSTR("UP"));
  txNumber(usbReceived);
  txNumber(usbCompleted);
  txByte(' ');
  txP(!hasResult ? PSTR("NONE") : outcome == OUTCOME_COMPLETED ? PSTR("COMPLETED") : outcome == OUTCOME_ABORTED ? PSTR("ABORTED") : PSTR("FAILED"));
  txByte(':');
  char code[13];
  reasonCode(code, sizeof(code));
  txRam(hasResult ? code : "NONE");
  txEnd();
}

static void sendHello() {
  txBegin(PSTR("HELLO 1 " PICASSO_FIRMWARE_VERSION " " PICASSO_DIALECT " " PICASSO_CONFIG_ID));
  txHex(bootId);
  txWordP(PSTR("STREAM,PAUSE,STOP,HOME"));
  txEnd();
}

static void sendReply(PGM_P kind, PGM_P command, PGM_P detail) {
  txBegin(kind);
  txWordP(command);
  if (detail) txWordP(detail);
  txEnd();
}

static void sendSequence(PGM_P kind, uint32_t sequence) {
  txBegin(kind);
  txNumber(sequence);
}

static void sendAck(uint32_t sequence, bool duplicate) {
  sendSequence(PSTR("ACK"), sequence);
  txFixed(posX);
  txFixed(posY);
  if (duplicate) txWordP(PSTR("DUP"));
  txEnd();
}

static void sendNak(uint32_t sequence, const char* code) {
  sendSequence(PSTR("NAK"), sequence);
  txWord(code);
  txEnd();
}

static void sendNakP(uint32_t sequence, PGM_P code) {
  sendSequence(PSTR("NAK"), sequence);
  txWordP(code);
  txEnd();
}

static void sendEvent(PGM_P event) {
  txBegin(PSTR("EVT"));
  txWordP(event);
  txJobKind();
  txNumber(usbCompleted);
  txFixed(posX);
  txFixed(posY);
  char code[13];
  reasonCode(code, sizeof(code));
  txWord(code);
  txEnd();
}

// -------------------------------------------------------------- menu views
static void enterMain() {
  mode = MODE_MAIN;
  clearText();
  textP(0, cursor == 0 ? PSTR("> SD job") : PSTR("  SD job"));
  textP(1, cursor == 1 ? PSTR("> Setup") : PSTR("  Setup"));
  textP(2, cursor == 2 ? PSTR("> Info") : PSTR("  Info"));
  originText(3);
  render();
}

static PGM_P setupLabel(uint8_t item) {
  switch (item) {
    case 0: return PSTR("Set origin");
    case 1: return PSTR("Jog ropes");
    case 2: return PSTR("Go to origin");
    case 3: return PSTR("Pen test");
    case 4: return PSTR("Test square");
    default: return PSTR("Release motors");
  }
}

static void enterSetup() {
  mode = MODE_SETUP;
  clearText();
  textP(0, PSTR("SETUP"));
  uint8_t first = cursor == 0 ? 0 : cursor - 1;
  if (first > kSetupItems - 3) first = kSetupItems - 3;
  for (uint8_t row = 0; row < 3; ++row) {
    uint8_t item = first + row;
    textP(row + 1, item == cursor ? PSTR("> ") : PSTR("  "));
    appendP(row + 1, setupLabel(item));
  }
  render();
}

static void showMessage(PGM_P first, PGM_P second, Mode back) {
  mode = MODE_MESSAGE;
  messageReturn = back;
  clearText();
  textP(0, first);
  textP(1, second);
  textP(3, PSTR("Any key"));
  render();
}

static void enterInfo() {
  mode = MODE_INFO;
  clearText();
  textP(0, PSTR("FW " PICASSO_FIRMWARE_VERSION));
  textP(1, PSTR("CFG ID"));
  textP(2, PSTR(PICASSO_CONFIG_ID));
  textP(3, geometry.hasRegion ? PSTR("Region: set") : PSTR("Region: none"));
  render();
}

static void enterConfirm(Confirm which) {
  mode = MODE_CONFIRM;
  confirming = which;
  clearText();
  if (which == CONFIRM_ORIGIN) {
    textP(0, PSTR("Pen at origin?"));
    textP(1, PSTR("Ropes taut?"));
  } else {
    textP(0, PSTR("Release motors?"));
    textP(1, PSTR("Origin is lost"));
  }
  textP(3, PSTR("ENT=yes ESC=no"));
  render();
}

static void enterJog() {
  mode = MODE_JOG;
  clearText();
  textP(0, PSTR("JOG  pen up"));
  textP(1, PSTR("> "));
  appendP(1, kJogLabels[cursor]);
  textP(2, PSTR("DOWN=next ENT=go"));
  textP(3, PSTR("ESC=back"));
  render();
}

static void enterPenTest() {
  mode = MODE_PEN_TEST;
  clearText();
  textP(0, PSTR("PEN TEST"));
  textP(1, penDown ? PSTR("Pen: down") : PSTR("Pen: up"));
  textP(2, PSTR("ENT=toggle"));
  textP(3, PSTR("ESC=back"));
  render();
}

// Parser/geometry status code, or a firmware-level reason, as text.
static void reasonString(char* out, size_t size) {
  if (reason == REASON_PARSE) picasso::statusCode(failure, out, size);
  else {
    strncpy_P(out, kReasons[reason], size - 1);
    out[size - 1] = '\0';
  }
}

static void logResult() {
  char text[16];
  reasonString(text, sizeof(text));
  Serial.print(F("PICASSO RESULT "));
  Serial.print(outcome == OUTCOME_COMPLETED ? F("COMPLETED") : outcome == OUTCOME_ABORTED ? F("ABORTED") : F("FAILED"));
  Serial.print(F(" LINE "));
  Serial.print(failedLine);
  Serial.print(F(" REASON "));
  Serial.print(text[0] ? text : "NONE");
  Serial.println(motionStarted ? F(" MOTION YES") : F(" MOTION NO"));
}

static void enterResult() {
  mode = MODE_RESULT;
  clearText();
  char number[11];
  if (outcome == OUTCOME_COMPLETED) {
    textP(0, PSTR("COMPLETED"));
    if (jobKind == JOB_SD) {
      formatHex(number, validatedCrc);
      textP(1, PSTR("CRC "));
      appendRam(1, number);
    }
  } else {
    textP(0, outcome == OUTCOME_ABORTED ? PSTR("ABORTED") : PSTR("FAILED"));
    char text[16];
    reasonString(text, sizeof(text));
    textRam(1, text);
    if (failedLine) {
      formatUnsigned(number, failedLine);
      textP(2, PSTR("Line "));
      appendRam(2, number);
    }
  }
  if (!motionStarted) textP(3, PSTR("No motion done"));
  else originText(3);
  render();
  logResult();
  hasResult = true;
  sendEvent(outcome == OUTCOME_COMPLETED ? PSTR("COMPLETED") : outcome == OUTCOME_ABORTED ? PSTR("ABORTED") : PSTR("FAILED"));
  if (outcome == OUTCOME_COMPLETED) startBeep(5, 300, 300);  // legacy completion pattern
  else if (outcome == OUTCOME_ABORTED) startBeep(2, 150, 150);
  else startBeep(1, 1500, 0);
}

static void closeJob() {
  if (jobKind != JOB_SD) return;
  if (jobFile) jobFile.close();
  SD.end();
}

// Failure before any motion: validation, card or file errors.
static void failBeforeMotion(Reason why, picasso::Status status, uint32_t line) {
  closeJob();
  outcome = OUTCOME_FAILED;
  reason = why;
  failure = status;
  failedLine = line;
  motionStarted = false;
  enterResult();
}

// ------------------------------------------------------------------ motion
static void beginLine(float x, float y) {
  planner.begin(posX, posY, x, y, geometry.tps);
  subTargetActive = false;
  motorBusy = false;
}

// One cooperative slice. With hold set, stops at the next sub-target
// boundary (at most one TPS of travel), leaving the position exactly known.
static MotionResult serviceMotion(bool hold) {
  if (motorBusy) {
    if (!activeMotor->processMovement()) return MOTION_BUSY;
    motorBusy = false;
  }
  if (subTargetActive) {
    uint8_t motor;
    int8_t direction;
    if (steps.next(motor, direction)) {
      activeMotor = motor == 1 ? &m1 : &m2;
      activeMotor->setupRelativeMoveInSteps(direction);
      motorBusy = true;
      return MOTION_BUSY;
    }
    rope1 = subRope1;
    rope2 = subRope2;
    posX = subX;
    posY = subY;
    subTargetActive = false;
  }
  if (hold) return MOTION_HELD;
  float x, y;
  if (!planner.next(x, y)) return MOTION_DONE;
  picasso::ik(geometry, x, y, subRope1, subRope2);
  steps.begin(rope1, rope2, subRope1, subRope2,
              PICASSO_M1_LENGTHEN, PICASSO_M1_SHORTEN, PICASSO_M2_LENGTHEN, PICASSO_M2_SHORTEN);
  subX = x;
  subY = y;
  subTargetActive = true;
  return MOTION_BUSY;
}

// --------------------------------------------------------------- execution
static void renderRunning() {
  clearText();
  textP(0, jobKind == JOB_SD ? PSTR("RUNNING main.nc") : jobKind == JOB_SQUARE ? PSTR("TEST SQUARE")
           : jobKind == JOB_USB ? PSTR("USB job") : PSTR("TO ORIGIN"));
  textP(2, PSTR("ENT=pause"));
  textP(3, PSTR("ESC=stop"));
  render();
}

static void startExecution(JobKind kind) {
  jobKind = kind;
  mode = MODE_EXECUTING;
  originFresh = false;  // motion consumes the operator's origin confirmation
  pauseRequested = stopRequested = false;
  stopReason = REASON_STOPPED;
  motionStarted = true;
  outcome = OUTCOME_COMPLETED;
  reason = REASON_NONE;
  failure = picasso::OK;
  failedLine = 0;
  current.empty = true;
  current.hasXY = false;
  commandPen(false);
  phase = EX_SETTLE;
  logEvent(kind == JOB_SD ? F("START SD") : kind == JOB_SQUARE ? F("START SQUARE") : kind == JOB_USB ? F("START USB") : F("START ORIGIN"));
  renderRunning();
}

static void endExecution(Outcome result, Reason why, picasso::Status status) {
  outcome = result;
  reason = why;
  failure = status;
  if (jobKind == JOB_SD && result != OUTCOME_COMPLETED) failedLine = reader.lineNumber();
  if (jobKind == JOB_USB && result != OUTCOME_COMPLETED) failedLine = usbReceived;  // sequence number
  commandPen(false);  // raise first; the display update can take tens of ms
  phase = EX_ENDING;
  logEvent(result == OUTCOME_ABORTED ? F("STOPPING") : result == OUTCOME_FAILED ? F("FAILING") : F("FINISHING"));
}

static Fetch fetchSdCommand() {
  for (uint8_t n = 0; n < PICASSO_READ_BYTES_PER_LOOP; ++n) {
    picasso::LineReader::Result result;
    if (bytesRead >= fileSize) {
      result = reader.finish();
      if (result == picasso::LineReader::NEED_MORE) {
        if (picasso::crc32Final(crc) != validatedCrc || reader.lineNumber() != validatedLines) {
          endExecution(OUTCOME_FAILED, REASON_FILE_CHANGED, picasso::OK);
          return FETCH_FAILED;
        }
        return FETCH_END;
      }
    } else {
      int value = jobFile.read();
      if (value < 0) {
        endExecution(OUTCOME_FAILED, REASON_SD_READ, picasso::OK);
        return FETCH_FAILED;
      }
      ++bytesRead;
      crc = picasso::crc32Update(crc, static_cast<uint8_t>(value));
      result = reader.feed(static_cast<uint8_t>(value));
      if (result == picasso::LineReader::NEED_MORE) continue;
    }
    if (result == picasso::LineReader::FAILED) {
      endExecution(OUTCOME_FAILED, REASON_PARSE, reader.error());
      return FETCH_FAILED;
    }
    picasso::Status status = picasso::parseLine(reader.line(), reader.length(), current);
    // The card is re-validated while running in case it changed after the check.
    if (status == picasso::OK) status = checker.accept(current);
    if (status != picasso::OK) {
      endExecution(OUTCOME_FAILED, REASON_PARSE, status);
      return FETCH_FAILED;
    }
    if (!current.empty) return FETCH_COMMAND;
  }
  return FETCH_BUSY;
}

// The first reason wins: keypad, host STOP or the host-loss watchdog.
static void requestStop(Reason why) {
  if (stopRequested) return;
  stopRequested = true;
  stopReason = why;
}

// A USB command is acknowledged only once its pen change and motion finished.
static void commandDone() {
  if (jobKind != JOB_USB || !usbInFlight) return;
  usbInFlight = false;
  usbCompleted = usbReceived;
  sendAck(usbCompleted, false);
}

static Fetch fetchCommand() {
  if (jobKind == JOB_SD) return fetchSdCommand();
  if (jobKind == JOB_USB) {
    if (!usbPending) return FETCH_BUSY;  // END from the host completes the job
    usbPending = false;
    usbInFlight = true;
    current = usbCommand;
    return FETCH_COMMAND;
  }
  if (programIndex >= programLength) return FETCH_END;
  current = program[programIndex++];
  return FETCH_COMMAND;
}

// Pause/stop take effect only here: between commands, during pen settling
// or at a motion sub-target boundary.
static void reachSafePoint() {
  if (stopRequested) {
    endExecution(OUTCOME_ABORTED, stopReason, picasso::OK);
    return;
  }
  pausedFrom = phase;
  resumePenDown = penDown;
  commandPen(false);
  phase = EX_PAUSING;
  logEvent(F("PAUSING"));
}

static void finishExecution() {
  closeJob();
  if (jobKind == JOB_USB && (usbPending || usbInFlight)) {
    // Received but not completed: it may have run partly; the event reports the position.
    sendNakP(usbReceived, PSTR("ABORTED"));
    usbPending = usbInFlight = false;
  }
  hostJob = false;
  if (PICASSO_RELEASE_AFTER_JOB) {
    m1.disableMotor();
    m2.disableMotor();
    invalidateOrigin();
  }
  enterResult();
}

// Resume always needs an explicit request (keypad ENTER or host RESUME).
static void resumeExecution() {
  pauseRequested = false;
  commandPen(resumePenDown);
  phase = EX_RESUMING;
  logEvent(F("RESUMING"));
  sendEvent(PSTR("RESUMED"));
  renderRunning();
}

static bool canPause() { return phase != EX_PAUSING && phase != EX_PAUSED && phase != EX_RESUMING && phase != EX_ENDING; }

static void serviceExecution(Key key) {
  if (key == KEY_ESC) requestStop(REASON_STOPPED);
  else if (key == KEY_ENTER) {
    if (phase == EX_PAUSED) {
      resumeExecution();
      return;
    }
    if (canPause()) pauseRequested = true;
  }
  switch (phase) {
    case EX_FETCH: {
      if (stopRequested || pauseRequested) {
        reachSafePoint();
        return;
      }
      Fetch fetched = fetchCommand();
      if (fetched == FETCH_END) endExecution(OUTCOME_COMPLETED, REASON_NONE, picasso::OK);
      else if (fetched == FETCH_COMMAND) {
        commandPen(!current.penUp);  // Z applies before the XY move, as in the legacy parser
        phase = EX_SETTLE;
      }
      return;
    }
    case EX_SETTLE:
      if (stopRequested || pauseRequested) {
        reachSafePoint();
        return;
      }
      if (!penSettled()) return;
      if (current.hasXY) {
        beginLine(current.x, current.y);
        phase = EX_MOVE;
      } else {
        phase = EX_FETCH;
        commandDone();
      }
      return;
    case EX_MOVE: {
      MotionResult result = serviceMotion(stopRequested || pauseRequested);
      if (result == MOTION_DONE) {
        phase = EX_FETCH;
        commandDone();
      } else if (result == MOTION_HELD) reachSafePoint();
      return;
    }
    case EX_PAUSING:
      if (!penSettled()) return;
      if (stopRequested) {
        endExecution(OUTCOME_ABORTED, stopReason, picasso::OK);
        return;
      }
      phase = EX_PAUSED;
      logEvent(F("PAUSED"));
      sendEvent(PSTR("PAUSED"));
      clearText();
      textP(0, PSTR("PAUSED  pen up"));
      textP(2, PSTR("ENT=resume"));
      textP(3, PSTR("ESC=stop"));
      render();
      return;
    case EX_PAUSED:
      if (stopRequested) endExecution(OUTCOME_ABORTED, stopReason, picasso::OK);
      return;
    case EX_RESUMING:
      if (penSettled()) phase = pausedFrom;
      return;
    case EX_ENDING:
      if (penSettled()) finishExecution();
      return;
  }
}

// ---------------------------------------------------------------- SD jobs
static void startSdValidation() {
  jobKind = JOB_SD;
  if (!geometry.hasRegion) {
    showMessage(PSTR("No workspace in"), PSTR("machine config"), MODE_MAIN);
    return;
  }
  if (!SD.begin(PICASSO_SD_CS_PIN)) {
    failBeforeMotion(REASON_SD_INIT, picasso::OK, 0);
    return;
  }
  jobFile = SD.open("main.nc");
  if (!jobFile) {
    failBeforeMotion(REASON_NO_FILE, picasso::OK, 0);
    return;
  }
  fileSize = jobFile.size();
  bytesRead = 0;
  crc = picasso::kCrcInitial;
  reader.reset();
  checker.begin(geometry, 0, 0);
  mode = MODE_VALIDATING;
  logEvent(F("VALIDATING"));
  clearText();
  textP(0, PSTR("Checking main.nc"));
  textP(1, PSTR("No motion yet"));
  textP(3, PSTR("ESC=cancel"));
  render();
}

static void enterReady() {
  mode = MODE_READY;
  clearText();
  char number[11];
  formatUnsigned(number, validatedMoves);
  textRam(0, number);
  appendP(0, PSTR(" moves OK"));
  formatHex(number, validatedCrc);
  textP(1, PSTR("CRC "));
  appendRam(1, number);
  textP(2, originFresh ? PSTR("ENT=start") : PSTR("Set origin 1st"));
  textP(3, PSTR("ESC=back"));
  render();
  Serial.print(F("PICASSO VALID MOVES "));
  Serial.print(validatedMoves);
  Serial.print(F(" CRC "));
  Serial.println(number);
}

static bool validateLine() {
  picasso::Status status = picasso::parseLine(reader.line(), reader.length(), current);
  if (status == picasso::OK) status = checker.accept(current);
  if (status != picasso::OK) {
    failBeforeMotion(REASON_PARSE, status, reader.lineNumber());
    return false;
  }
  return true;
}

static void serviceValidation(Key key) {
  if (key == KEY_ESC) {
    closeJob();
    enterMain();
    return;
  }
  for (uint8_t n = 0; n < PICASSO_READ_BYTES_PER_LOOP; ++n) {
    if (bytesRead >= fileSize) {
      picasso::LineReader::Result result = reader.finish();
      if (result == picasso::LineReader::FAILED) {
        failBeforeMotion(REASON_PARSE, reader.error(), reader.lineNumber());
        return;
      }
      if (result == picasso::LineReader::LINE && !validateLine()) return;
      if (checker.moves() == 0) {
        failBeforeMotion(REASON_NO_MOVES, picasso::OK, 0);
        return;
      }
      validatedCrc = picasso::crc32Final(crc);
      validatedLines = reader.lineNumber();
      validatedMoves = checker.moves();
      enterReady();
      return;
    }
    int value = jobFile.read();
    if (value < 0) {
      failBeforeMotion(REASON_SD_READ, picasso::OK, reader.lineNumber() + 1);
      return;
    }
    ++bytesRead;
    crc = picasso::crc32Update(crc, static_cast<uint8_t>(value));
    picasso::LineReader::Result result = reader.feed(static_cast<uint8_t>(value));
    if (result == picasso::LineReader::FAILED) {
      failBeforeMotion(REASON_PARSE, reader.error(), reader.lineNumber());
      return;
    }
    if (result == picasso::LineReader::LINE && !validateLine()) return;
  }
}

static void startSdRun() {
  if (!jobFile.seek(0)) {
    failBeforeMotion(REASON_SD_READ, picasso::OK, 0);
    return;
  }
  bytesRead = 0;
  crc = picasso::kCrcInitial;
  reader.reset();
  checker.begin(geometry, 0, 0);
  startExecution(JOB_SD);
}

// ------------------------------------------------------- built-in programs
static void programMove(uint8_t g, float x, float y) {
  picasso::Command& command = program[programLength++];
  command.empty = false;
  command.hasXY = true;
  command.penUp = g == 0;
  command.g = g;
  command.x = x;
  command.y = y;
}

static void programPenUp() {
  picasso::Command& command = program[programLength++];
  command.empty = false;
  command.hasXY = false;
  command.penUp = true;
  command.g = 0;
  command.x = command.y = 0;
}

// Validates the whole program from the current position before any motion.
static bool startProgram(JobKind kind) {
  jobKind = kind;
  picasso::Status status = checker.begin(geometry, posX, posY);
  for (uint8_t i = 0; status == picasso::OK && i < programLength; ++i) status = checker.accept(program[i]);
  if (status != picasso::OK) {
    failBeforeMotion(REASON_PARSE, status, 0);
    return false;
  }
  programIndex = 0;
  startExecution(kind);
  return true;
}

static void startTestSquare() {
  if (!geometry.hasRegion) {
    showMessage(PSTR("No workspace in"), PSTR("machine config"), MODE_SETUP);
    return;
  }
  if (!originFresh) {
    showMessage(PSTR("Set origin"), PSTR("before a job"), MODE_SETUP);
    return;
  }
  const float half = PICASSO_TEST_SQUARE_MM / 2;
  programLength = 0;
  programPenUp();
  programMove(0, -half, -half);
  programMove(1, half, -half);
  programMove(1, half, half);
  programMove(1, -half, half);
  programMove(1, -half, -half);
  programPenUp();
  programMove(0, 0, 0);
  startProgram(JOB_SQUARE);
}

static void startGoToOrigin() {
  if (!geometry.hasRegion) {
    showMessage(PSTR("No workspace in"), PSTR("machine config"), MODE_SETUP);
    return;
  }
  if (!originValid) {
    showMessage(PSTR("Origin unknown"), PSTR("Jog, then set"), MODE_SETUP);
    return;
  }
  programLength = 0;
  programPenUp();
  programMove(0, 0, 0);
  startProgram(JOB_ORIGIN);
}

// --------------------------------------------------------------------- jog
static void serviceJog(Key key) {
  if (jogRemaining) {
    if (key == KEY_ESC) jogRemaining = 1;  // finish the current step only
    if (motorBusy && !activeMotor->processMovement()) return;
    motorBusy = false;
    if (--jogRemaining == 0) {
      logEvent(F("JOG DONE"));
      return;
    }
    activeMotor->setupRelativeMoveInSteps(jogDirection);
    motorBusy = true;
    return;
  }
  if (key == KEY_DOWN) {
    cursor = (cursor + 1) % 4;
    enterJog();
  } else if (key == KEY_ESC) {
    cursor = 1;
    enterSetup();
  } else if (key == KEY_ENTER && penSettled()) {
    // Rope-only moves: Cartesian position becomes unknown until set again.
    invalidateOrigin();
    activeMotor = cursor < 2 ? &m1 : &m2;
    bool lengthen = cursor % 2 == 0;
    if (cursor < 2) jogDirection = lengthen ? PICASSO_M1_LENGTHEN : PICASSO_M1_SHORTEN;
    else jogDirection = lengthen ? PICASSO_M2_LENGTHEN : PICASSO_M2_SHORTEN;
    activeMotor->setupRelativeMoveInSteps(jogDirection);
    motorBusy = true;
    jogRemaining = PICASSO_JOG_STEPS;
    logEvent(F("JOG"));
  }
}

// ------------------------------------------------------------- menu input
static void handleMenuKey(Key key) {
  if (key == KEY_NONE) return;
  switch (mode) {
    case MODE_MAIN:
      if (key == KEY_DOWN) {
        cursor = (cursor + 1) % kMainItems;
        enterMain();
      } else if (key == KEY_ENTER) {
        if (cursor == 0) startSdValidation();
        else if (cursor == 1) {
          cursor = 0;
          enterSetup();
        } else enterInfo();
      }
      return;
    case MODE_SETUP:
      if (key == KEY_DOWN) {
        cursor = (cursor + 1) % kSetupItems;
        enterSetup();
      } else if (key == KEY_ESC) {
        cursor = 1;
        enterMain();
      } else if (key == KEY_ENTER) {
        switch (cursor) {
          case 0: enterConfirm(CONFIRM_ORIGIN); break;
          case 1:
            commandPen(false);
            cursor = 0;
            enterJog();
            break;
          case 2: startGoToOrigin(); break;
          case 3: enterPenTest(); break;
          case 4: startTestSquare(); break;
          default: enterConfirm(CONFIRM_RELEASE); break;
        }
      }
      return;
    case MODE_CONFIRM:
      if (key == KEY_ENTER) {
        if (confirming == CONFIRM_ORIGIN) {
          commandPen(false);
          setOrigin();
        } else {
          m1.disableMotor();
          m2.disableMotor();
          invalidateOrigin();
          logEvent(F("MOTORS RELEASED"));
        }
        cursor = 0;
        enterMain();
      } else if (key == KEY_ESC) {
        cursor = confirming == CONFIRM_ORIGIN ? 0 : kSetupItems - 1;
        enterSetup();
      }
      return;
    case MODE_PEN_TEST:
      if (key == KEY_ENTER) {
        commandPen(!penDown);
        enterPenTest();
      } else if (key == KEY_ESC) {
        commandPen(false);
        cursor = 3;
        enterSetup();
      }
      return;
    case MODE_READY:
      if (key == KEY_ENTER && originFresh && posX == 0 && posY == 0) startSdRun();
      else if (key == KEY_ESC) {
        closeJob();
        enterMain();
      }
      return;
    case MODE_INFO:
    case MODE_RESULT:
      cursor = 0;
      enterMain();
      return;
    case MODE_MESSAGE:
      if (messageReturn == MODE_SETUP) enterSetup();
      else enterMain();
      return;
    default:
      return;
  }
}

// ------------------------------------------------------- protocol frames in
static bool parseHex32(const char* text, uint32_t& value) {
  uint32_t result = 0;
  uint8_t digits = 0;
  for (; *text; ++text, ++digits) {
    char ch = *text;
    uint8_t nibble;
    if (ch >= '0' && ch <= '9') nibble = static_cast<uint8_t>(ch - '0');
    else if (ch >= 'a' && ch <= 'f') nibble = static_cast<uint8_t>(ch - 'a' + 10);
    else return false;
    if (digits >= 8) return false;
    result = (result << 4) | nibble;
  }
  value = result;
  return digits == 8;
}

static bool sessionMatches(const char* boot, const char* revision, PGM_P command) {
  uint32_t expectedBoot, expectedRevision;
  if (!parseHex32(boot, expectedBoot) || !picasso::parseUnsigned(revision, expectedRevision)) {
    sendReply(PSTR("ERR"), command, PSTR("ARGS"));
    return false;
  }
  if (expectedBoot != bootId) {
    sendReply(PSTR("ERR"), command, PSTR("SESSION"));
    return false;
  }
  if (expectedRevision != originRevision) {
    sendReply(PSTR("ERR"), command, PSTR("REFERENCE"));
    return false;
  }
  return true;
}

static bool ownUsbJob() { return mode == MODE_EXECUTING && jobKind == JOB_USB; }

// BEGIN <token> <x> <y> <boot> <orev>: binds a USB job to this boot, origin
// reference and commanded position. It never moves to satisfy them.
static void handleBegin(char** words, uint8_t count) {
  PGM_P command = PSTR("BEGIN");
  float x, y;
  uint32_t token;
  if (count != 6 || !parseHex32(words[1], token) || !picasso::parseDecimal(words[2], x) || !picasso::parseDecimal(words[3], y)) {
    sendReply(PSTR("ERR"), command, PSTR("ARGS"));
    return;
  }
  if (!deviceIdle()) {
    sendReply(PSTR("ERR"), command, PSTR("STATE"));
    return;
  }
  if (!geometry.hasRegion) {
    sendReply(PSTR("ERR"), command, PSTR("NO_REGION"));
    return;
  }
  if (!originValid) {
    sendReply(PSTR("ERR"), command, PSTR("NO_ORIGIN"));
    return;
  }
  if (!sessionMatches(words[4], words[5], command)) return;
  if (fabs(posX - x) > 0.0005f || fabs(posY - y) > 0.0005f) {
    sendReply(PSTR("ERR"), command, PSTR("POSITION"));
    return;
  }
  strncpy(usbToken, words[1], sizeof(usbToken) - 1);
  usbToken[sizeof(usbToken) - 1] = '\0';
  usbReceived = usbCompleted = 0;
  usbPending = usbInFlight = false;
  jobKind = JOB_USB;
  checker.begin(geometry, posX, posY);
  hostJob = true;
  startExecution(JOB_USB);
  txBegin(PSTR("OK BEGIN"));
  txWord(usbToken);
  txEnd();
}

// M <seq> <gcode>: validated on receipt, acknowledged after completion.
static void handleMotion(char* rest) {
  char* payload = strchr(rest, ' ');
  if (payload) *payload++ = '\0';
  else payload = rest + strlen(rest);
  uint32_t sequence;
  if (!picasso::parseUnsigned(rest, sequence) || sequence == 0) {
    sendReply(PSTR("ERR"), PSTR("M"), PSTR("ARGS"));
    return;
  }
  if (!ownUsbJob() || phase == EX_ENDING) {
    sendNakP(sequence, PSTR("STATE"));
    return;
  }
  if (sequence == usbReceived && (usbPending || usbInFlight)) {  // repeated while running
    sendSequence(PSTR("RCV"), sequence);
    txWordP(PSTR("DUP"));
    txEnd();
    return;
  }
  if (sequence <= usbCompleted) {  // already executed: never again
    sendAck(sequence, true);
    return;
  }
  if (usbPending || usbInFlight) {
    sendNakP(sequence, PSTR("BUSY"));
    return;
  }
  if (sequence != usbReceived + 1) {
    sendNakP(sequence, PSTR("SEQUENCE"));
    usbReceived = sequence;
    endExecution(OUTCOME_FAILED, REASON_SEQUENCE, picasso::OK);
    return;
  }
  size_t length = strlen(payload);
  picasso::Status status = length > picasso::kLinePayload ? picasso::ERR_LINE_TOO_LONG
                         : picasso::parseLine(payload, static_cast<uint8_t>(length), usbCommand);
  if (status == picasso::OK) status = checker.accept(usbCommand);
  usbReceived = sequence;
  if (status != picasso::OK) {
    char code[12];
    picasso::statusCode(status, code, sizeof(code));
    sendNak(sequence, code);
    endExecution(OUTCOME_FAILED, REASON_PARSE, status);
    return;
  }
  sendSequence(PSTR("RCV"), sequence);
  txEnd();
  if (usbCommand.empty) {
    usbCompleted = sequence;
    sendAck(sequence, false);
  } else {
    usbPending = true;
  }
}

static void handleHome(char** words, uint8_t count) {
  PGM_P command = PSTR("HOME");
  if (count != 3) {
    sendReply(PSTR("ERR"), command, PSTR("ARGS"));
    return;
  }
  if (!deviceIdle()) {
    sendReply(PSTR("ERR"), command, PSTR("STATE"));
    return;
  }
  if (!geometry.hasRegion) {
    sendReply(PSTR("ERR"), command, PSTR("NO_REGION"));
    return;
  }
  if (!originValid) {
    sendReply(PSTR("ERR"), command, PSTR("NO_ORIGIN"));
    return;
  }
  if (!sessionMatches(words[1], words[2], command)) return;
  programLength = 0;
  programPenUp();
  programMove(0, 0, 0);
  hostJob = true;
  if (!startProgram(JOB_ORIGIN)) {  // the validated route leaves the workspace
    hostJob = false;
    sendReply(PSTR("ERR"), command, PSTR("PATH"));
    return;
  }
  sendReply(PSTR("OK"), command, 0);
}

static void handleFrame(char* body) {
  hostSeenAt = millis();
  if (body[0] == 'M' && body[1] == ' ') {
    handleMotion(body + 2);
    return;
  }
  char* words[7];
  uint8_t count = 0;
  for (char* word = strtok(body, " "); word; word = strtok(0, " ")) {
    if (count == 7) {
      sendReply(PSTR("ERR"), PSTR("FRAME"), PSTR("ARGS"));
      return;
    }
    words[count++] = word;
  }
  if (!count) return;
  const char* command = words[0];
  if (!strcmp_P(command, PSTR("HELLO"))) {
    if (count == 2 && !strcmp_P(words[1], PSTR("1"))) sendHello();
    else sendReply(PSTR("ERR"), PSTR("HELLO"), PSTR("VERSION 1"));
  } else if (!strcmp_P(command, PSTR("STATUS"))) {
    sendStatus();
  } else if (!strcmp_P(command, PSTR("BEGIN"))) {
    handleBegin(words, count);
  } else if (!strcmp_P(command, PSTR("END"))) {
    if (count != 2 || !ownUsbJob() || strcmp(words[1], usbToken)) sendReply(PSTR("ERR"), PSTR("END"), PSTR("STATE"));
    else if (usbPending || usbInFlight || phase != EX_FETCH || pauseRequested || stopRequested) sendReply(PSTR("ERR"), PSTR("END"), PSTR("BUSY"));
    else {
      endExecution(OUTCOME_COMPLETED, REASON_NONE, picasso::OK);
      txBegin(PSTR("OK END"));
      txWord(usbToken);
      txEnd();
    }
  } else if (!strcmp_P(command, PSTR("PAUSE"))) {
    if (ownUsbJob() && canPause()) {
      pauseRequested = true;
      sendReply(PSTR("OK"), PSTR("PAUSE"), 0);
    } else sendReply(PSTR("ERR"), PSTR("PAUSE"), PSTR("STATE"));
  } else if (!strcmp_P(command, PSTR("RESUME"))) {
    if (ownUsbJob() && phase == EX_PAUSED && !stopRequested) {
      resumeExecution();
      sendReply(PSTR("OK"), PSTR("RESUME"), 0);
    } else sendReply(PSTR("ERR"), PSTR("RESUME"), PSTR("STATE"));
  } else if (!strcmp_P(command, PSTR("STOP"))) {
    if (mode == MODE_EXECUTING && phase != EX_ENDING) {
      requestStop(REASON_HOST_STOP);
      sendReply(PSTR("OK"), PSTR("STOP"), 0);
    } else sendReply(PSTR("ERR"), PSTR("STOP"), PSTR("STATE"));
  } else if (!strcmp_P(command, PSTR("HOME"))) {
    handleHome(words, count);
  } else {
    sendReply(PSTR("ERR"), PSTR("FRAME"), PSTR("UNKNOWN"));
  }
}

static void serviceSerial() {
  for (uint8_t budget = 0; budget < 64 && Serial.available() > 0; ++budget) {
    int value = Serial.read();
    if (value < 0) return;
    picasso::FrameReader::Result result = frames.feed(static_cast<uint8_t>(value));
    if (result == picasso::FrameReader::FRAME) handleFrame(frames.body());
    else if (result == picasso::FrameReader::REJECTED) {
      static const char kFrameErrors[][7] PROGMEM = {"OK", "LONG", "CRC", "FORMAT", "BYTE"};
      sendReply(PSTR("ERR"), PSTR("FRAME"), kFrameErrors[frames.error()]);
    }
  }
  // Host-loss watchdog: a host-started job never continues without its host.
  if (mode == MODE_EXECUTING && hostJob && !stopRequested && millis() - hostSeenAt > PICASSO_HOST_TIMEOUT_MS) {
    requestStop(REASON_HOST_LOST);
  }
}

// ------------------------------------------------------------ entry points
void setup() {
  Serial.begin(PICASSO_BAUD);
  pinMode(PICASSO_BEEP_PIN, OUTPUT);
  digitalWrite(PICASSO_BEEP_PIN, LOW);
  u8x8.begin();
  u8x8.setFont(u8x8_font_amstrad_cpc_extended_r);

  m1.connectToPins(PICASSO_LEFT_IN1, PICASSO_LEFT_IN2, PICASSO_LEFT_IN3, PICASSO_LEFT_IN4);
  m2.connectToPins(PICASSO_RIGHT_IN1, PICASSO_RIGHT_IN2, PICASSO_RIGHT_IN3, PICASSO_RIGHT_IN4);
  m1.setSpeedInStepsPerSecond(PICASSO_STEPPER_SPEED);
  m1.setAccelerationInStepsPerSecondPerSecond(PICASSO_STEPPER_ACCELERATION);
  m2.setSpeedInStepsPerSecond(PICASSO_STEPPER_SPEED);
  m2.setAccelerationInStepsPerSecondPerSecond(PICASSO_STEPPER_ACCELERATION);

  pen.attach(PICASSO_SERVO_PIN);
  pen.write(PICASSO_PEN_UP_DEGREES);
  penDown = false;
  penChangedAt = millis();
  penSettleMs = PICASSO_PEN_UP_SETTLE_MS;

  geometry = picasso::makeGeometry(PICASSO_SEPARATION_MM, PICASSO_ANCHOR_Y_MM, PICASSO_SPOOL_DIAMETER_MM, PICASSO_STEPS_PER_TURN);
#if PICASSO_HAS_REGION
  picasso::setRegion(geometry, PICASSO_REGION_MIN_X_MM, PICASSO_REGION_MAX_X_MM, PICASSO_REGION_MIN_Y_MM,
                     PICASSO_REGION_MAX_Y_MM, PICASSO_REGION_MARGIN_MM, PICASSO_ROPE_MIN_MM, PICASSO_ROPE_MAX_MM);
#endif

  // A new boot ID for every reset lets a host detect that position is unknown.
  EEPROM.get(PICASSO_EEPROM_BOOT_ADDRESS, bootId);
  ++bootId;
  EEPROM.put(PICASSO_EEPROM_BOOT_ADDRESS, bootId);
  frames.reset();

  // Informational log line; protocol frames start with '@' (docs/SERIAL_PROTOCOL.md).
  Serial.print(F("PICASSO FW " PICASSO_FIRMWARE_VERSION " DIALECT " PICASSO_DIALECT " CFG " PICASSO_CONFIG_ID));
  Serial.println(geometry.hasRegion ? F(" REGION SET ORIGIN UNSET") : F(" REGION NONE ORIGIN UNSET"));

  clearText();
  textP(0, PSTR("Picasso " PICASSO_FIRMWARE_VERSION));
  textP(1, PSTR(PICASSO_CONFIG_ID));
  textP(3, PSTR("Origin: unset"));
  render();
  delay(1500);
  txBegin(PSTR("BOOT"));
  txHex(bootId);
  txWordP(PSTR("1"));
  txEnd();
  enterMain();
}

void loop() {
  serviceSerial();
  serviceBeep();
  Key key = pollKey();
  switch (mode) {
    case MODE_EXECUTING: serviceExecution(key); break;
    case MODE_VALIDATING: serviceValidation(key); break;
    case MODE_JOG: serviceJog(key); break;
    default: handleMenuKey(key); break;
  }
}
