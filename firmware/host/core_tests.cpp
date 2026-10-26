// Host unit tests for picasso_core. Build: python3 scripts/firmware.py host-test
#include "picasso_core.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

using namespace picasso;

static int failures = 0, checks = 0;

#define CHECK(condition)                                                     \
  do {                                                                       \
    ++checks;                                                                \
    if (!(condition)) {                                                      \
      ++failures;                                                            \
      std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition);       \
    }                                                                        \
  } while (0)

static Status parse(const char* text, Command& command) {
  return parseLine(text, static_cast<uint8_t>(std::strlen(text)), command);
}

static Status parse(const char* text) {
  Command command;
  return parse(text, command);
}

struct Read {
  std::vector<std::string> lines;
  Status error;
  uint32_t errorLine;
};

static Read readAll(const std::string& bytes) {
  LineReader reader;
  reader.reset();
  Read result = {{}, OK, 0};
  for (unsigned char byte : bytes) {
    LineReader::Result step = reader.feed(byte);
    if (step == LineReader::LINE) result.lines.push_back(reader.line());
    if (step == LineReader::FAILED) {
      result.error = reader.error();
      result.errorLine = reader.lineNumber();
      return result;
    }
  }
  LineReader::Result last = reader.finish();
  if (last == LineReader::LINE) result.lines.push_back(reader.line());
  if (last == LineReader::FAILED) {
    result.error = reader.error();
    result.errorLine = reader.lineNumber();
  }
  CHECK(reader.finish() != LineReader::LINE);  // EOF is reported once
  return result;
}

static void testReader() {
  Read lf = readAll("G0 Z5\nG1 X1.000 Y2.000 Z0\n");
  CHECK(lf.error == OK && lf.lines.size() == 2 && lf.lines[1] == "G1 X1.000 Y2.000 Z0");
  Read crlf = readAll("G0 Z5\r\nG0 X1 Y1 Z5\r\n");
  CHECK(crlf.error == OK && crlf.lines.size() == 2 && crlf.lines[0] == "G0 Z5");
  Read residual = readAll("G0 Z5\nG0 X1 Y1 Z5");  // legacy dropped this final line
  CHECK(residual.error == OK && residual.lines.size() == 2 && residual.lines[1] == "G0 X1 Y1 Z5");
  Read blank = readAll("\n\nG0 Z5\n");
  CHECK(blank.error == OK && blank.lines.size() == 3 && blank.lines[0].empty());
  CHECK(readAll("G0 Z5\rG0 Z5\n").error == ERR_BARE_CR);
  CHECK(readAll("G0 Z5\r").error == ERR_BARE_CR);
  Read nul = readAll(std::string("G0 Z5\nG0\0 Z5\n", 13));
  CHECK(nul.error == ERR_BAD_BYTE && nul.errorLine == 2);
  CHECK(readAll("G0 Z5 \xC2\xB0\n").error == ERR_BAD_BYTE);
  CHECK(readAll("G0\tZ5\n").error == OK);
  std::string exact(63, ' ');
  exact.replace(0, 5, "G0 Z5");
  CHECK(readAll(exact + "\n").error == OK);
  CHECK(readAll(exact + "\r\n").error == OK);  // CR is not payload
  Read overflow = readAll("G0 Z5\n" + exact + " \n");
  CHECK(overflow.error == ERR_LINE_TOO_LONG && overflow.errorLine == 2);
}

static void testParser() {
  Command c;
  CHECK(parse("G0 Z5", c) == OK && !c.empty && !c.hasXY && c.penUp && c.g == 0);
  CHECK(parse("G0 X-10.000 Y12.500 Z5", c) == OK && c.hasXY && c.penUp && c.x == -10.0f && c.y == 12.5f);
  CHECK(parse("G1 X10.000 Y-10.000 Z0", c) == OK && c.hasXY && !c.penUp && c.g == 1 && c.y == -10.0f);
  CHECK(parse("G1 Z0", c) == OK && !c.hasXY && !c.penUp);
  // Synonyms, case, word order and spacing.
  CHECK(parse("G00 X1 Y2 Z5", c) == OK && c.g == 0 && c.x == 1.0f);
  CHECK(parse("g01 x1 y2 z-1", c) == OK && c.g == 1 && !c.penUp);
  CHECK(parse("G1 Z0 Y2.5 X-3", c) == OK && c.x == -3.0f && c.y == 2.5f);  // legacy misparsed reordered words
  CHECK(parse("G1X1Y2Z0", c) == OK && c.x == 1.0f && c.y == 2.0f);
  CHECK(parse("  G0\tX+.5 Y-0.25 Z5  ", c) == OK && c.x == 0.5f && c.y == -0.25f);
  // Comments never act, even when they contain coordinate letters.
  CHECK(parse("; Centre = X139.7 Y177.8", c) == OK && c.empty);
  CHECK(parse("; Pen up = Z3.0", c) == OK && c.empty);
  CHECK(parse("(X1 Y2 Z0)", c) == OK && c.empty);
  CHECK(parse("G0 X1 Y2 Z5 ; then X9 Y9 Z0", c) == OK && c.x == 1.0f && c.penUp);
  CHECK(parse("G1 (draw X9) X3 Y4 Z0", c) == OK && c.x == 3.0f && c.y == 4.0f);
  CHECK(parse("", c) == OK && c.empty);
  CHECK(parse("   ", c) == OK && c.empty);
  CHECK(parse("G0 (open X1") == ERR_COMMENT);
  CHECK(parse("G0 ((nested)) Z5") == ERR_COMMENT);
  CHECK(parse("G0 ) Z5") == ERR_COMMENT);
  // Missing, duplicate and conflicting fields.
  CHECK(parse("X1 Y2 Z0") == ERR_MISSING_G);
  CHECK(parse("G1 X1 Y2") == ERR_MISSING_Z);
  CHECK(parse("G0") == ERR_MISSING_Z);
  CHECK(parse("G1 X10 Z0") == ERR_MISSING_AXIS);
  CHECK(parse("G1 Y10 Z0") == ERR_MISSING_AXIS);
  CHECK(parse("G1 X1 X2 Y2 Z0") == ERR_DUPLICATE);
  CHECK(parse("G1 X1 Y2 Z0 Z0") == ERR_DUPLICATE);
  CHECK(parse("G1 G0 Z5") == ERR_DUPLICATE);
  CHECK(parse("G0 X1 Y1 Z0") == ERR_PEN_MODE);
  CHECK(parse("G1 X1 Y1 Z5") == ERR_PEN_MODE);
  CHECK(parse("G0 Z0") == ERR_PEN_MODE);
  // Unsupported opcodes and words are rejected, not silently skipped.
  CHECK(parse("G2 X1 Y1 Z0") == ERR_UNSUPPORTED_G);
  CHECK(parse("G28 Z5") == ERR_UNSUPPORTED_G);
  CHECK(parse("G90") == ERR_UNSUPPORTED_G);
  CHECK(parse("G001 Z5") == ERR_UNSUPPORTED_G);
  CHECK(parse("G1.0 X1 Y1 Z0") == ERR_UNSUPPORTED_G);
  CHECK(parse("G-1 Z5") == ERR_UNSUPPORTED_G);
  CHECK(parse("M3") == ERR_WORD);
  CHECK(parse("G1 X1 Y1 Z0 F1500") == ERR_WORD);
  CHECK(parse("N10 G0 Z5") == ERR_WORD);
  CHECK(parse("G0 X1 Y1 I2 Z5") == ERR_WORD);
  CHECK(parse("%") == ERR_WORD);
  // Malformed numbers.
  CHECK(parse("G0 X Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X- Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X. Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X1.2.3 Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X1e3 Y1 Z5") == ERR_WORD);
  CHECK(parse("G0 X1,5 Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X--1 Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X12345 Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X1.123456 Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 XNAN Y1 Z5") == ERR_NUMBER);
  CHECK(parse("G0 X1 Y1 Z5*71") == ERR_NUMBER);
  CHECK(parse("G0 X9999.99999 Y-9999.99999 Z5", c) == OK && std::fabs(c.x - 9999.99999f) < 1e-3f);
}

static Geometry fixture() {
  Geometry geometry = makeGeometry(350, 250, 35, 2048);
  setRegion(geometry, -150, 150, -100, 160, 5, 100, 600);
  return geometry;
}

static void testGeometry() {
  Geometry geometry = makeGeometry(350, 250, 35, 2048);
  CHECK(std::fabs(geometry.tps - 0.0536895f) < 1e-6f);
  long left, right;
  ik(geometry, 0, 0, left, right);
  // sqrt(175^2 + 250^2) / TPS
  CHECK(left == right && left == std::lround(std::sqrt(175.0 * 175.0 + 250.0 * 250.0) / geometry.tps));
  ik(geometry, -175, 0, left, right);
  CHECK(left == std::lround(250.0 / geometry.tps));
  Geometry wide = makeGeometry(400, 250, 35, 2048);
  ik(wide, 0, 0, left, right);
  CHECK(left == std::lround(std::sqrt(200.0 * 200.0 + 250.0 * 250.0) / wide.tps));
  CHECK(checkPoint(geometry, 0, 0) == ERR_NO_REGION);

  Geometry g = fixture();
  CHECK(checkPoint(g, 0, 0) == OK);
  CHECK(checkPoint(g, 145, -95) == OK);
  CHECK(checkPoint(g, 145.005f, 0) == OK);  // float tolerance
  CHECK(checkPoint(g, 145.02f, 0) == ERR_OUT_OF_REGION);
  CHECK(checkPoint(g, 0, -95.02f) == ERR_OUT_OF_REGION);
  CHECK(checkPoint(g, -145.02f, 0) == ERR_OUT_OF_REGION);
  CHECK(checkPoint(g, NAN, 0) == ERR_OUT_OF_REGION);
  Geometry branch = g;
  branch.branchMaxY = 100;
  CHECK(checkPoint(branch, 0, 100.02f) == ERR_ANCHOR_BRANCH);
  CHECK(checkPoint(branch, 0, 100) == OK);  // within float tolerance of the limit
  CHECK(checkSegment(g, 0, 0, 100, 100) == OK);
  // Left anchor (-175, 250): rope minimum 100 + half a step.
  CHECK(checkSegment(g, -140, 0, -140, 140) == OK);                // closest ~115.4 mm
  CHECK(checkSegment(g, -145, 100, -145, 155) == ERR_ROPE_LIMIT);  // endpoint ~99.6 mm
  Geometry tight = fixture();
  setRegion(tight, -150, 150, -100, 160, 5, 100, 380);
  CHECK(checkSegment(tight, 0, 0, 0, -95) == ERR_ROPE_LIMIT);  // sqrt(175^2 + 345^2) ~ 386.8
  CHECK(checkSegment(tight, 0, 0, 0, -80) == OK);              // ~ 373.5
  // Interior minimum: both endpoints clear the limit (~100.2 and ~77.6 mm),
  // the closest interior point (~69.8 mm) does not.
  Geometry near = makeGeometry(350, 250, 35, 2048);
  setRegion(near, -170, 170, -100, 240, 1, 72, 600);
  CHECK(checkSegment(near, -169, 150, -169, 150) == OK);
  CHECK(checkSegment(near, -100, 230, -100, 230) == OK);
  CHECK(checkSegment(near, -169, 150, -100, 230) == ERR_ROPE_LIMIT);
  setRegion(near, -170, 170, -100, 240, 1, 65, 600);
  CHECK(checkSegment(near, -169, 150, -100, 230) == OK);

  JobChecker checker;
  CHECK(checker.begin(g, 0, 0) == OK);
  Command c;
  parse("G0 X10 Y10 Z5", c);
  CHECK(checker.accept(c) == OK);
  parse("G1 Z0", c);
  CHECK(checker.accept(c) == OK);
  parse("G1 X200 Y10 Z0", c);
  CHECK(checker.accept(c) == ERR_OUT_OF_REGION);
  CHECK(checker.moves() == 1);
  CHECK(checker.begin(g, 300, 0) == ERR_OUT_OF_REGION);  // a job start is validated too
}

// Verbatim re-implementation of the reference sketch's line_safe()/moveto().
struct Legacy {
  Geometry geometry;
  float posx, posy;
  long last1, last2;
  std::vector<std::pair<int, int>> events;

  void IK(float x, float y, long& l1, long& l2) {
    float dy = y - geometry.anchorY;
    float dx = x - (-geometry.halfSeparation);
    l1 = std::lround(std::sqrt(dx * dx + dy * dy) / geometry.tps);
    dx = x - geometry.halfSeparation;
    l2 = std::lround(std::sqrt(dx * dx + dy * dy) / geometry.tps);
  }
  void moveto(float x, float y) {
    long l1, l2;
    IK(x, y, l1, l2);
    long d1 = l1 - last1, d2 = l2 - last2;
    long ad1 = std::labs(d1), ad2 = std::labs(d2);
    int dir1 = d1 > 0 ? 1 : -1;   // M1_REEL_IN : M1_REEL_OUT
    int dir2 = d2 > 0 ? -1 : 1;   // M2_REEL_IN : M2_REEL_OUT
    long over = 0;
    if (ad1 > ad2) {
      for (long i = 0; i < ad1; ++i) {
        events.push_back({1, dir1});
        over += ad2;
        if (over >= ad1) {
          over -= ad1;
          events.push_back({2, dir2});
        }
      }
    } else {
      for (long i = 0; i < ad2; ++i) {
        events.push_back({2, dir2});
        over += ad1;
        if (over >= ad2) {
          over -= ad2;
          events.push_back({1, dir1});
        }
      }
    }
    last1 = l1;
    last2 = l2;
    posx = x;
    posy = y;
  }
  void line_safe(float x, float y) {
    float dx = x - posx, dy = y - posy;
    float len = std::sqrt(dx * dx + dy * dy);
    if (len <= geometry.tps) {
      moveto(x, y);
      return;
    }
    long pieces = static_cast<long>(std::floor(len / geometry.tps));
    float x0 = posx, y0 = posy, a;
    for (long j = 0; j <= pieces; ++j) {
      a = static_cast<float>(j) / static_cast<float>(pieces);
      moveto((x - x0) * a + x0, (y - y0) * a + y0);
    }
    moveto(x, y);
  }
};

struct Cooperative {
  Geometry geometry;
  float posx, posy;
  long rope1, rope2;
  std::vector<std::pair<int, int>> events;

  void line(float x, float y) {
    LinePlanner planner;
    planner.begin(posx, posy, x, y, geometry.tps);
    float tx, ty;
    while (planner.next(tx, ty)) {
      long l1, l2;
      ik(geometry, tx, ty, l1, l2);
      StepIterator iterator;
      iterator.begin(rope1, rope2, l1, l2, 1, -1, -1, 1);
      uint8_t motor;
      int8_t direction;
      while (iterator.next(motor, direction)) events.push_back({motor, direction});
      rope1 = l1;
      rope2 = l2;
      posx = tx;
      posy = ty;
    }
  }
};

static void testLegacyEquivalence() {
  const float separations[] = {350, 400};
  for (float separation : separations) {
    Geometry geometry = makeGeometry(separation, 250, 35, 2048);
    Legacy legacy{geometry, 0, 0, 0, 0, {}};
    Cooperative cooperative{geometry, 0, 0, 0, 0, {}};
    legacy.IK(0, 0, legacy.last1, legacy.last2);
    ik(geometry, 0, 0, cooperative.rope1, cooperative.rope2);
    CHECK(legacy.last1 == cooperative.rope1 && legacy.last2 == cooperative.rope2);
    uint32_t seed = 12345;
    auto random = [&seed](float low, float high) {
      seed = seed * 1103515245u + 12345u;
      return low + (high - low) * ((seed >> 8) & 0xFFFF) / 65535.0f;
    };
    for (int i = 0; i < 400; ++i) {
      float x, y;
      if (i % 10 == 0) {  // sub-TPS and zero-length moves
        x = legacy.posx + random(-0.05f, 0.05f);
        y = legacy.posy + (i % 20 == 0 ? 0 : random(-0.05f, 0.05f));
      } else {
        x = random(-120, 120);
        y = random(-90, 140);
      }
      legacy.line_safe(x, y);
      cooperative.line(x, y);
    }
    CHECK(!legacy.events.empty());
    CHECK(legacy.events == cooperative.events);
    CHECK(legacy.last1 == cooperative.rope1 && legacy.last2 == cooperative.rope2);
    CHECK(legacy.posx == cooperative.posx && legacy.posy == cooperative.posy);
    long motor1 = 0, motor2 = 0;
    for (const auto& event : cooperative.events) (event.first == 1 ? motor1 : motor2) += event.second;
    long origin1, origin2;
    ik(geometry, 0, 0, origin1, origin2);
    // Lengthening rope 1 uses +1 and rope 2 uses -1 (legacy direction constants).
    CHECK(motor1 == cooperative.rope1 - origin1 && motor2 == -(cooperative.rope2 - origin2));
  }
}

static void testCrc() {
  uint32_t crc = kCrcInitial;
  for (const char* p = "123456789"; *p; ++p) crc = crc32Update(crc, static_cast<uint8_t>(*p));
  CHECK(crc32Final(crc) == 0xCBF43926UL);
  char code[12];
  statusCode(ERR_ROPE_LIMIT, code, sizeof(code));
  CHECK(std::strcmp(code, "ROPE_LIMIT") == 0);
  statusCode(OK, code, 3);
  CHECK(std::strcmp(code, "OK") == 0);
}

static std::string frame(const std::string& body) {
  uint16_t crc = kCrc16Initial;
  for (char ch : body) crc = crc16Update(crc, static_cast<uint8_t>(ch));
  char hex[5];
  std::snprintf(hex, sizeof(hex), "%04X", crc);
  return "@" + body + "*" + hex + "\n";
}

struct Framed {
  std::vector<std::string> bodies;
  std::vector<FrameError> errors;
};

static Framed feedFrames(const std::string& bytes) {
  FrameReader reader;
  reader.reset();
  Framed result;
  for (unsigned char byte : bytes) {
    FrameReader::Result step = reader.feed(byte);
    if (step == FrameReader::FRAME) result.bodies.push_back(reader.body());
    if (step == FrameReader::REJECTED) result.errors.push_back(reader.error());
  }
  return result;
}

static void testFraming() {
  uint16_t crc = kCrc16Initial;
  for (const char* p = "123456789"; *p; ++p) crc = crc16Update(crc, static_cast<uint8_t>(*p));
  CHECK(crc == 0x29B1);  // CRC-16/CCITT-FALSE check value
  Framed good = feedFrames(frame("STATUS") + "PICASSO log line\n" + frame("M 1 G0 X1.000 Y2.000 Z5"));
  CHECK(good.errors.empty() && good.bodies.size() == 2 && good.bodies[1] == "M 1 G0 X1.000 Y2.000 Z5");
  std::string crlf = frame("HELLO 1");
  crlf.insert(crlf.size() - 1, "\r");
  CHECK(feedFrames(crlf).bodies.size() == 1);
  std::string corrupt = frame("M 2 G1 X1.000 Y2.000 Z0");
  corrupt[6] = '9';
  Framed bad = feedFrames(corrupt);
  CHECK(bad.bodies.empty() && bad.errors.size() == 1 && bad.errors[0] == FRAME_CRC);
  CHECK(feedFrames("@STATUS*12G4\n").errors[0] == FRAME_FORMAT);
  CHECK(feedFrames("@STATUS\n").errors[0] == FRAME_FORMAT);
  CHECK(feedFrames(frame("A*B")).errors[0] == FRAME_FORMAT);
  CHECK(feedFrames(frame(std::string(90, 'X'))).bodies.size() == 1);
  CHECK(feedFrames(frame(std::string(91, 'X'))).errors[0] == FRAME_LONG);
  CHECK(feedFrames("@" + std::string(200, 'X') + "\n").errors[0] == FRAME_LONG);
  CHECK(feedFrames("@STA\x01TUS*0000\n").errors[0] == FRAME_BYTE);
  // A new '@' resynchronises after garbage or a truncated frame.
  Framed resync = feedFrames("@M 3 G0 X1" + frame("STOP"));
  CHECK(resync.bodies.size() == 1 && resync.bodies[0] == "STOP" && resync.errors.empty());
  uint32_t value = 0;
  CHECK(parseUnsigned("4294967295", value) && value == 4294967295UL);
  CHECK(!parseUnsigned("4294967296", value) && !parseUnsigned("", value) && !parseUnsigned("12a", value) && !parseUnsigned("-1", value));
  float number = 0;
  CHECK(parseDecimal("-12.345", number) && number == -12.345f);
  CHECK(!parseDecimal("1.2.3", number) && !parseDecimal("1e3", number) && !parseDecimal("", number) && !parseDecimal("12 ", number));
}

int main() {
  testFraming();
  testReader();
  testParser();
  testGeometry();
  testLegacyEquivalence();
  testCrc();
  std::printf("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
