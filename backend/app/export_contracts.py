"""Export Pydantic contracts for TypeScript generation; --check detects drift."""

import argparse
import json

from pydantic import TypeAdapter

from .main import ROOT
from .models import ALL_CONTRACTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "frontend" / "schema" / "contracts.json"
    schema = TypeAdapter(ALL_CONTRACTS).json_schema()
    schema["title"] = "PicassoContracts"
    content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("Backend contracts changed. Run npm run contracts in frontend/.")
        print("Backend JSON schema is current.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print("Exported backend contracts.")


if __name__ == "__main__":
    main()
