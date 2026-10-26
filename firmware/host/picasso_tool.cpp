// Host access to picasso_core for cross-checks against the backend.
//   picasso_tool parse < file
//       Reads bytes exactly like the firmware; one result per line, then EOF.
//   picasso_tool geometry SEP ANCHOR SPOOL STEPS [MINX MAXX MINY MAXY MARGIN ROPEMIN ROPEMAX] < queries
//       Queries: "ik X Y", "point X Y", "seg X0 Y0 X1 Y1".
#include "picasso_core.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace picasso;

static void printStatus(uint32_t line, Status status) {
  char code[12];
  statusCode(status, code, sizeof(code));
  std::printf("%u ERR %s\n", static_cast<unsigned>(line), code);
}

static void printCode(Status status) {
  char code[12];
  statusCode(status, code, sizeof(code));
  std::printf("%s\n", code);
}

static int parseInput() {
  LineReader reader;
  reader.reset();
  int byte;
  bool more = true;
  while (more) {
    byte = std::getchar();
    LineReader::Result result = byte == EOF ? reader.finish() : reader.feed(static_cast<uint8_t>(byte));
    if (byte == EOF && result == LineReader::NEED_MORE) break;
    if (result == LineReader::NEED_MORE) continue;
    if (result == LineReader::FAILED) {
      printStatus(reader.lineNumber(), reader.error());
      return 0;
    }
    Command command;
    Status status = parseLine(reader.line(), reader.length(), command);
    if (status != OK) printStatus(reader.lineNumber(), status);
    else if (command.empty) std::printf("%u OK EMPTY\n", static_cast<unsigned>(reader.lineNumber()));
    else if (command.hasXY) {
      std::printf("%u OK G%u %s %.9g %.9g\n", static_cast<unsigned>(reader.lineNumber()), command.g,
                  command.penUp ? "UP" : "DOWN", command.x, command.y);
    } else {
      std::printf("%u OK G%u %s\n", static_cast<unsigned>(reader.lineNumber()), command.g, command.penUp ? "UP" : "DOWN");
    }
    more = byte != EOF;
  }
  std::printf("EOF\n");
  return 0;
}

static int geometryQueries(int argc, char** argv) {
  if (argc != 6 && argc != 13) return 2;
  Geometry geometry = makeGeometry(std::strtof(argv[2], 0), std::strtof(argv[3], 0), std::strtof(argv[4], 0), std::strtol(argv[5], 0, 10));
  if (argc == 13) {
    setRegion(geometry, std::strtof(argv[6], 0), std::strtof(argv[7], 0), std::strtof(argv[8], 0), std::strtof(argv[9], 0),
              std::strtof(argv[10], 0), std::strtof(argv[11], 0), std::strtof(argv[12], 0));
  }
  char kind[8];
  float a, b, c, d;
  while (std::scanf("%7s", kind) == 1) {
    if (std::strcmp(kind, "ik") == 0 && std::scanf("%f %f", &a, &b) == 2) {
      long left, right;
      ik(geometry, a, b, left, right);
      std::printf("%ld %ld\n", left, right);
    } else if (std::strcmp(kind, "point") == 0 && std::scanf("%f %f", &a, &b) == 2) {
      printCode(checkPoint(geometry, a, b));
    } else if (std::strcmp(kind, "seg") == 0 && std::scanf("%f %f %f %f", &a, &b, &c, &d) == 4) {
      printCode(checkSegment(geometry, a, b, c, d));
    } else {
      return 2;
    }
  }
  return 0;
}

int main(int argc, char** argv) {
  if (argc >= 2 && std::strcmp(argv[1], "parse") == 0) return parseInput();
  if (argc >= 2 && std::strcmp(argv[1], "geometry") == 0) return geometryQueries(argc, argv);
  std::fprintf(stderr, "usage: picasso_tool parse | geometry SEP ANCHOR SPOOL STEPS [region...]\n");
  return 2;
}
