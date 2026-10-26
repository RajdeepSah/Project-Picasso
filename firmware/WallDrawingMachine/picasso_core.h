// Portable Picasso firmware core: bounded line reading, strict SD dialect
// parsing, rope kinematics, workspace checks and legacy-equivalent stepping.
// No Arduino dependencies, so the same source is tested on the host.
#ifndef PICASSO_CORE_H
#define PICASSO_CORE_H

#include <stdint.h>
#include <stddef.h>

namespace picasso {

// Payload bytes per line, excluding CR/LF. Matches the host G-code contract.
const uint8_t kLinePayload = 63;
// Firmware limits are a second check after host validation. They accept
// values within this float tolerance of a limit so float32 arithmetic never
// rejects a job the host approved at exactly the boundary.
const float kToleranceMm = 0.01f;

enum Status : uint8_t {
  OK = 0,
  ERR_LINE_TOO_LONG,
  ERR_BARE_CR,
  ERR_BAD_BYTE,
  ERR_COMMENT,
  ERR_WORD,
  ERR_NUMBER,
  ERR_DUPLICATE,
  ERR_MISSING_G,
  ERR_UNSUPPORTED_G,
  ERR_MISSING_Z,
  ERR_MISSING_AXIS,
  ERR_PEN_MODE,
  ERR_NO_REGION,
  ERR_OUT_OF_REGION,
  ERR_ANCHOR_BRANCH,
  ERR_ROPE_LIMIT,
  STATUS_COUNT
};

// Copies a short (<= 12 character) code such as "BAD_NUMBER" into out.
void statusCode(Status status, char* out, size_t size);

class LineReader {
 public:
  enum Result : uint8_t { NEED_MORE, LINE, FAILED };
  void reset();
  // Feed one file byte. LINE means line()/length() hold a complete line.
  Result feed(uint8_t byte);
  // Call at end of file: returns LINE for an unterminated final line.
  Result finish();
  const char* line() const { return buffer_; }
  uint8_t length() const { return length_; }
  Status error() const { return error_; }
  // 1-based number of the line just returned or rejected.
  uint32_t lineNumber() const { return number_; }

 private:
  Result fail(Status status);
  char buffer_[kLinePayload + 1];
  uint8_t length_;
  bool carriageReturn_;
  bool complete_;
  Status error_;
  uint32_t number_;
};

struct Command {
  bool empty;    // blank or comment-only line: no action
  bool hasXY;
  bool penUp;    // Z > 0 raises; Z <= 0 lowers (legacy mapping)
  uint8_t g;     // 0 travel, 1 draw
  float x;
  float y;
};

// Strict "picasso-fw-v1" dialect: one G0/G1 (or G00/G01) word, mandatory Z,
// X and Y together or not at all, each word at most once in any order.
// G0 requires Z > 0 and G1 requires Z <= 0. ';' and '( )' comments are
// removed first, so coordinate letters inside comments never act.
Status parseLine(const char* line, uint8_t length, Command& command);

struct Geometry {
  float halfSeparation;
  float anchorY;
  float tps;          // rope millimetres per full step
  bool hasRegion;
  float minX, maxX, minY, maxY;  // interior after the measured margin
  float branchMaxY;   // anchor line minus margin
  float ropeMin;      // measured minimum plus half a step
  float ropeMax;      // measured maximum minus half a step
};

Geometry makeGeometry(float separation, float anchorY, float spoolDiameter, long stepsPerTurn);
void setRegion(Geometry& geometry, float minX, float maxX, float minY, float maxY, float margin,
               float ropeMin, float ropeMax);

// Legacy IK(): rope lengths in whole steps, measured from each anchor.
void ik(const Geometry& geometry, float x, float y, long& left, long& right);
Status checkPoint(const Geometry& geometry, float x, float y);
Status checkSegment(const Geometry& geometry, float x0, float y0, float x1, float y1);

// Simulates a job from its declared start and validates every motion.
class JobChecker {
 public:
  Status begin(const Geometry& geometry, float startX, float startY);
  Status accept(const Command& command);
  uint32_t moves() const { return moves_; }

 private:
  const Geometry* geometry_;
  float x_, y_;
  uint32_t moves_;
};

// Sub-targets of legacy line_safe(): pieces of at most one TPS, including
// the legacy start point and duplicate final endpoint.
class LinePlanner {
 public:
  void begin(float x0, float y0, float x1, float y1, float tps);
  bool next(float& x, float& y);

 private:
  float x0_, y0_, x1_, y1_;
  long pieces_, index_;
  uint8_t stage_;
};

// Step events of legacy moveto(): Bresenham interleave, major motor first,
// ties choose motor 2 as the major axis, exactly as the original sketch.
class StepIterator {
 public:
  void begin(long from1, long from2, long to1, long to2,
             int8_t lengthen1, int8_t shorten1, int8_t lengthen2, int8_t shorten2);
  bool next(uint8_t& motor, int8_t& direction);

 private:
  long major_, minor_, index_, over_;
  int8_t direction1_, direction2_;
  bool motor1Major_, pendingMinor_;
};

uint32_t crc32Update(uint32_t crc, uint8_t byte);
const uint32_t kCrcInitial = 0xFFFFFFFFUL;
inline uint32_t crc32Final(uint32_t crc) { return ~crc; }

}  // namespace picasso

#endif
