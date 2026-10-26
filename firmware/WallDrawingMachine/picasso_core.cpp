#include "picasso_core.h"

#include <math.h>
#include <string.h>

#if defined(__AVR__)
#include <avr/pgmspace.h>
// AVR double is binary32, so these are the operations the legacy sketch used.
#define PICASSO_SQRT(value) sqrt(value)
#define PICASSO_LROUND(value) lround(value)
#define PICASSO_FLOOR(value) floor(value)
#define PICASSO_COPY_FLASH(target, source, size) strncpy_P(target, source, size)
#else
#define PROGMEM
#define PICASSO_SQRT(value) sqrtf(value)
#define PICASSO_LROUND(value) lroundf(value)
#define PICASSO_FLOOR(value) floorf(value)
#define PICASSO_COPY_FLASH(target, source, size) strncpy(target, source, size)
#endif

namespace picasso {

static const char kStatusCodes[STATUS_COUNT][12] PROGMEM = {
  "OK", "LINE_LONG", "BARE_CR", "BAD_BYTE", "COMMENT", "BAD_WORD", "BAD_NUMBER", "DUP_WORD",
  "MISSING_G", "UNSUP_G", "MISSING_Z", "MISSING_XY", "PEN_MODE", "NO_REGION", "OUT_REGION",
  "ANCHOR_LINE", "ROPE_LIMIT",
};

void statusCode(Status status, char* out, size_t size) {
  if (size == 0) return;
  if (status >= STATUS_COUNT) status = ERR_WORD;
  PICASSO_COPY_FLASH(out, kStatusCodes[status], size - 1);
  out[size - 1] = '\0';
}

// ---------------------------------------------------------------- reader

void LineReader::reset() {
  length_ = 0;
  carriageReturn_ = false;
  complete_ = false;
  error_ = OK;
  number_ = 0;
  buffer_[0] = '\0';
}

LineReader::Result LineReader::fail(Status status) {
  ++number_;
  error_ = status;
  length_ = 0;
  buffer_[0] = '\0';
  return FAILED;
}

LineReader::Result LineReader::feed(uint8_t byte) {
  if (error_ != OK) return FAILED;
  if (complete_) {
    length_ = 0;
    complete_ = false;
  }
  if (byte == '\n') {
    ++number_;
    carriageReturn_ = false;
    complete_ = true;
    buffer_[length_] = '\0';
    return LINE;
  }
  // CR is accepted only as part of CRLF.
  if (carriageReturn_) return fail(ERR_BARE_CR);
  if (byte == '\r') {
    carriageReturn_ = true;
    return NEED_MORE;
  }
  if (byte == 0 || byte > 0x7E || (byte < 0x20 && byte != '\t')) return fail(ERR_BAD_BYTE);
  if (length_ >= kLinePayload) return fail(ERR_LINE_TOO_LONG);
  buffer_[length_++] = static_cast<char>(byte);
  return NEED_MORE;
}

LineReader::Result LineReader::finish() {
  if (error_ != OK) return FAILED;
  if (complete_) {
    length_ = 0;
    complete_ = false;
  }
  if (carriageReturn_) return fail(ERR_BARE_CR);
  if (length_ == 0) return NEED_MORE;
  // The legacy reader silently dropped an unterminated final line.
  ++number_;
  complete_ = true;
  buffer_[length_] = '\0';
  return LINE;
}

// ---------------------------------------------------------------- parser

static bool isDigit(char ch) { return ch >= '0' && ch <= '9'; }
static bool isSpace(char ch) { return ch == ' ' || ch == '\t'; }
static bool isLetter(char ch) { return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z'); }
static char upper(char ch) { return (ch >= 'a' && ch <= 'z') ? static_cast<char>(ch - 'a' + 'A') : ch; }

static const float kPowersOfTen[6] = {1.0f, 10.0f, 100.0f, 1000.0f, 10000.0f, 100000.0f};

// Fixed decimal only: optional sign, at most 4 integer and 5 fraction digits.
static bool parseNumber(const char* text, uint8_t length, uint8_t& index, float& value) {
  bool negative = false;
  if (index < length && (text[index] == '+' || text[index] == '-')) {
    negative = text[index] == '-';
    ++index;
  }
  int32_t mantissa = 0;
  uint8_t integerDigits = 0, fractionDigits = 0;
  while (index < length && isDigit(text[index])) {
    if (++integerDigits > 4) return false;
    mantissa = mantissa * 10 + (text[index++] - '0');
  }
  if (index < length && text[index] == '.') {
    ++index;
    while (index < length && isDigit(text[index])) {
      if (++fractionDigits > 5) return false;
      mantissa = mantissa * 10 + (text[index++] - '0');
    }
  }
  if (integerDigits + fractionDigits == 0) return false;
  if (index < length && !isSpace(text[index]) && !isLetter(text[index])) return false;
  value = static_cast<float>(mantissa) / kPowersOfTen[fractionDigits];
  if (negative) value = -value;
  return true;
}

Status parseLine(const char* line, uint8_t length, Command& command) {
  char text[kLinePayload + 1];
  uint8_t size = 0;
  bool comment = false;
  if (length > kLinePayload) return ERR_LINE_TOO_LONG;
  for (uint8_t i = 0; i < length; ++i) {
    char ch = line[i];
    if (comment) {
      if (ch == ')') comment = false;
      else if (ch == '(') return ERR_COMMENT;
      continue;
    }
    if (ch == ';') break;
    if (ch == '(') {
      comment = true;
      continue;
    }
    if (ch == ')') return ERR_COMMENT;
    text[size++] = ch;
  }
  if (comment) return ERR_COMMENT;

  bool seenG = false, seenX = false, seenY = false, seenZ = false;
  float x = 0, y = 0, z = 0;
  uint8_t g = 0;
  uint8_t index = 0;
  while (index < size) {
    if (isSpace(text[index])) {
      ++index;
      continue;
    }
    char letter = upper(text[index++]);
    if (letter == 'G') {
      if (seenG) return ERR_DUPLICATE;
      seenG = true;
      uint8_t digits = 0, value = 0;
      while (index < size && isDigit(text[index])) {
        value = static_cast<uint8_t>(value * 10 + (text[index++] - '0'));
        if (++digits > 2) return ERR_UNSUPPORTED_G;
      }
      if (digits == 0 || value > 1) return ERR_UNSUPPORTED_G;
      if (index < size && !isSpace(text[index]) && !isLetter(text[index])) return ERR_UNSUPPORTED_G;
      g = value;
      continue;
    }
    float* target;
    bool* seen;
    if (letter == 'X') { target = &x; seen = &seenX; }
    else if (letter == 'Y') { target = &y; seen = &seenY; }
    else if (letter == 'Z') { target = &z; seen = &seenZ; }
    else return ERR_WORD;
    if (*seen) return ERR_DUPLICATE;
    *seen = true;
    if (!parseNumber(text, size, index, *target)) return ERR_NUMBER;
  }

  command.empty = !(seenG || seenX || seenY || seenZ);
  command.hasXY = false;
  command.penUp = true;
  command.g = 0;
  command.x = command.y = 0;
  if (command.empty) return OK;
  if (!seenG) return ERR_MISSING_G;
  if (!seenZ) return ERR_MISSING_Z;
  if (seenX != seenY) return ERR_MISSING_AXIS;
  bool penUp = z > 0;
  if ((g == 0) != penUp) return ERR_PEN_MODE;
  command.hasXY = seenX;
  command.penUp = penUp;
  command.g = g;
  command.x = x;
  command.y = y;
  return OK;
}

// ------------------------------------------------------------- geometry

Geometry makeGeometry(float separation, float anchorY, float spoolDiameter, long stepsPerTurn) {
  Geometry geometry;
  geometry.halfSeparation = separation * 0.5f;
  geometry.anchorY = anchorY;
  // Legacy TPS: SPOOL_DIAMETER * 3.1416 / STEPS_PER_TURN.
  geometry.tps = spoolDiameter * 3.1416f / static_cast<float>(stepsPerTurn);
  geometry.hasRegion = false;
  geometry.minX = geometry.maxX = geometry.minY = geometry.maxY = 0;
  geometry.branchMaxY = anchorY;
  geometry.ropeMin = geometry.ropeMax = 0;
  return geometry;
}

void setRegion(Geometry& geometry, float minX, float maxX, float minY, float maxY, float margin,
               float ropeMin, float ropeMax) {
  float halfStep = geometry.tps * 0.5f;
  geometry.hasRegion = true;
  geometry.minX = minX + margin;
  geometry.maxX = maxX - margin;
  geometry.minY = minY + margin;
  geometry.maxY = maxY - margin;
  geometry.branchMaxY = geometry.anchorY - margin;
  geometry.ropeMin = ropeMin + halfStep;
  geometry.ropeMax = ropeMax - halfStep;
}

void ik(const Geometry& geometry, float x, float y, long& left, long& right) {
  float dy = y - geometry.anchorY;
  float dx = x - (-geometry.halfSeparation);
  left = PICASSO_LROUND(PICASSO_SQRT(dx * dx + dy * dy) / geometry.tps);
  dx = x - geometry.halfSeparation;
  right = PICASSO_LROUND(PICASSO_SQRT(dx * dx + dy * dy) / geometry.tps);
}

Status checkPoint(const Geometry& geometry, float x, float y) {
  if (!geometry.hasRegion) return ERR_NO_REGION;
  if (!(x >= geometry.minX - kToleranceMm && x <= geometry.maxX + kToleranceMm &&
        y >= geometry.minY - kToleranceMm && y <= geometry.maxY + kToleranceMm)) {
    return ERR_OUT_OF_REGION;
  }
  if (!(y < geometry.branchMaxY + kToleranceMm)) return ERR_ANCHOR_BRANCH;
  return OK;
}

static float distance(float x0, float y0, float x1, float y1) {
  float dx = x1 - x0, dy = y1 - y0;
  return PICASSO_SQRT(dx * dx + dy * dy);
}

// Same projection as backend geometry.segment_distance().
static float segmentDistance(float px, float py, float x0, float y0, float x1, float y1) {
  float dx = x1 - x0, dy = y1 - y0;
  float squared = dx * dx + dy * dy;
  if (squared == 0) return distance(px, py, x0, y0);
  float t = ((px - x0) * dx + (py - y0) * dy) / squared;
  if (t < 0) t = 0;
  if (t > 1) t = 1;
  return distance(px, py, x0 + t * dx, y0 + t * dy);
}

Status checkSegment(const Geometry& geometry, float x0, float y0, float x1, float y1) {
  Status status = checkPoint(geometry, x0, y0);
  if (status != OK) return status;
  status = checkPoint(geometry, x1, y1);
  if (status != OK) return status;
  // The region and branch half-plane are convex, so endpoints bound them;
  // rope length is convex along the segment, so its maximum is an endpoint.
  for (int8_t side = -1; side <= 1; side += 2) {
    float ax = side * geometry.halfSeparation;
    float shortest = segmentDistance(ax, geometry.anchorY, x0, y0, x1, y1);
    float a = distance(ax, geometry.anchorY, x0, y0);
    float b = distance(ax, geometry.anchorY, x1, y1);
    float longest = a > b ? a : b;
    if (shortest < geometry.ropeMin - kToleranceMm || longest > geometry.ropeMax + kToleranceMm) {
      return ERR_ROPE_LIMIT;
    }
  }
  return OK;
}

Status JobChecker::begin(const Geometry& geometry, float startX, float startY) {
  geometry_ = &geometry;
  x_ = startX;
  y_ = startY;
  moves_ = 0;
  return checkPoint(geometry, startX, startY);
}

Status JobChecker::accept(const Command& command) {
  if (command.empty || !command.hasXY) return OK;
  Status status = checkSegment(*geometry_, x_, y_, command.x, command.y);
  if (status != OK) return status;
  x_ = command.x;
  y_ = command.y;
  ++moves_;
  return OK;
}

// --------------------------------------------------------------- motion

void LinePlanner::begin(float x0, float y0, float x1, float y1, float tps) {
  x0_ = x0;
  y0_ = y0;
  x1_ = x1;
  y1_ = y1;
  index_ = 0;
  float dx = x1 - x0;
  float dy = y1 - y0;
  float length = PICASSO_SQRT(dx * dx + dy * dy);
  if (length <= tps) {
    pieces_ = 0;
    stage_ = 2;
  } else {
    pieces_ = static_cast<long>(PICASSO_FLOOR(length / tps));
    stage_ = 1;
  }
}

bool LinePlanner::next(float& x, float& y) {
  if (stage_ == 1) {
    float a = static_cast<float>(index_) / static_cast<float>(pieces_);
    x = (x1_ - x0_) * a + x0_;
    y = (y1_ - y0_) * a + y0_;
    if (++index_ > pieces_) stage_ = 2;
    return true;
  }
  if (stage_ == 2) {
    x = x1_;
    y = y1_;
    stage_ = 3;
    return true;
  }
  return false;
}

void StepIterator::begin(long from1, long from2, long to1, long to2,
                         int8_t lengthen1, int8_t shorten1, int8_t lengthen2, int8_t shorten2) {
  long d1 = to1 - from1;
  long d2 = to2 - from2;
  long ad1 = d1 < 0 ? -d1 : d1;
  long ad2 = d2 < 0 ? -d2 : d2;
  direction1_ = d1 > 0 ? lengthen1 : shorten1;
  direction2_ = d2 > 0 ? lengthen2 : shorten2;
  motor1Major_ = ad1 > ad2;
  major_ = motor1Major_ ? ad1 : ad2;
  minor_ = motor1Major_ ? ad2 : ad1;
  index_ = 0;
  over_ = 0;
  pendingMinor_ = false;
}

bool StepIterator::next(uint8_t& motor, int8_t& direction) {
  if (pendingMinor_) {
    pendingMinor_ = false;
    motor = motor1Major_ ? 2 : 1;
    direction = motor1Major_ ? direction2_ : direction1_;
    return true;
  }
  if (index_ >= major_) return false;
  ++index_;
  motor = motor1Major_ ? 1 : 2;
  direction = motor1Major_ ? direction1_ : direction2_;
  over_ += minor_;
  if (over_ >= major_) {
    over_ -= major_;
    pendingMinor_ = true;
  }
  return true;
}

uint32_t crc32Update(uint32_t crc, uint8_t byte) {
  crc ^= byte;
  for (uint8_t bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320UL & (0UL - (crc & 1UL)));
  return crc;
}

// ------------------------------------------------------------- framing

uint16_t crc16Update(uint16_t crc, uint8_t byte) {
  crc ^= static_cast<uint16_t>(byte) << 8;
  for (uint8_t bit = 0; bit < 8; ++bit) crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021) : static_cast<uint16_t>(crc << 1);
  return crc;
}

enum FrameState : uint8_t { WAITING, IN_FRAME, DISCARDING };

void FrameReader::reset() {
  length_ = 0;
  state_ = WAITING;
  error_ = FRAME_OK;
  buffer_[0] = '\0';
}

FrameReader::Result FrameReader::reject(FrameError error) {
  error_ = error;
  state_ = WAITING;
  length_ = 0;
  buffer_[0] = '\0';
  return REJECTED;
}

static int8_t hexValue(char ch) {
  if (ch >= '0' && ch <= '9') return static_cast<int8_t>(ch - '0');
  if (ch >= 'A' && ch <= 'F') return static_cast<int8_t>(ch - 'A' + 10);
  return -1;
}

FrameReader::Result FrameReader::feed(uint8_t byte) {
  if (byte == '@') {  // a new frame always resynchronises
    state_ = IN_FRAME;
    length_ = 0;
    error_ = FRAME_OK;
    return NONE;
  }
  if (state_ == WAITING) return NONE;
  if (byte == '\n') {
    if (state_ == DISCARDING) return reject(error_);
    uint8_t size = length_;
    if (size && buffer_[size - 1] == '\r') --size;
    if (size < 5 || buffer_[size - 5] != '*') return reject(FRAME_FORMAT);
    uint16_t expected = 0;
    for (uint8_t i = size - 4; i < size; ++i) {
      int8_t digit = hexValue(buffer_[i]);
      if (digit < 0) return reject(FRAME_FORMAT);
      expected = static_cast<uint16_t>((expected << 4) | digit);
    }
    uint8_t bodyLength = size - 5;
    if (bodyLength > kFrameBody) return reject(FRAME_LONG);
    uint16_t crc = kCrc16Initial;
    for (uint8_t i = 0; i < bodyLength; ++i) {
      if (buffer_[i] == '*') return reject(FRAME_FORMAT);
      crc = crc16Update(crc, static_cast<uint8_t>(buffer_[i]));
    }
    if (crc != expected) return reject(FRAME_CRC);
    buffer_[bodyLength] = '\0';
    length_ = bodyLength;
    state_ = WAITING;
    error_ = FRAME_OK;
    return FRAME;
  }
  if (state_ == DISCARDING) return NONE;
  if (byte != '\r' && (byte < 0x20 || byte > 0x7E)) {
    error_ = FRAME_BYTE;
    state_ = DISCARDING;
    return NONE;
  }
  if (length_ >= sizeof(buffer_) - 1) {
    error_ = FRAME_LONG;
    state_ = DISCARDING;
    return NONE;
  }
  buffer_[length_++] = static_cast<char>(byte);
  return NONE;
}

bool parseUnsigned(const char* text, uint32_t& value) {
  uint8_t digits = 0;
  uint32_t result = 0;
  for (; *text; ++text) {
    if (!isDigit(*text) || ++digits > 10) return false;
    uint32_t next = result * 10 + static_cast<uint32_t>(*text - '0');
    if (next / 10 != result) return false;  // overflow
    result = next;
  }
  if (!digits) return false;
  value = result;
  return true;
}

bool parseDecimal(const char* text, float& value) {
  size_t length = strlen(text);
  if (length == 0 || length > kLinePayload) return false;
  uint8_t index = 0;
  return parseNumber(text, static_cast<uint8_t>(length), index, value) && index == length;
}

}  // namespace picasso
