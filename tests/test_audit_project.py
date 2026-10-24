"""Check audit interpretation boundaries without hardware or third-party packages."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_project.py"
spec = importlib.util.spec_from_file_location("audit_project", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class GcodeInspectionTests(unittest.TestCase):
    def test_explicit_bounds_exclude_comments_and_preserve_modal_warning(self):
        report = audit.inspect_gcode(b"G21\nG90\nG1 X-1.5 Y+2.0 F500 ; X999\nG1 X3 (Y888)\nG0 Z5\nM2\n")
        self.assertEqual(report["explicit_coordinate_bounds_mm_assumed"]["X"], {"min": -1.5, "max": 3})
        self.assertEqual(report["explicit_coordinate_bounds_mm_assumed"]["Y"], {"min": 2, "max": 2})
        self.assertEqual(report["commands"], {"G0": 1, "G1": 2, "G21": 1, "G90": 1, "M2": 1})
        self.assertEqual(report["lexical_flags"]["lines_with_only_one_xy_axis"], 1)
        self.assertEqual(report["lexical_flags"]["lines_with_comments"], 2)
        self.assertEqual(report["lexical_flags"]["standalone_z_lines"], 1)
        self.assertTrue(report["ends_with_lf"])

    def test_missing_final_lf_and_noncanonical_axis_order_are_visible(self):
        report = audit.inspect_gcode(b"g1 y.25 x-.5 z0")
        self.assertFalse(report["ends_with_lf"])
        self.assertEqual(report["lexical_flags"]["lines_with_y_before_x"], 1)
        self.assertEqual(report["explicit_coordinate_bounds_mm_assumed"]["X"]["min"], -0.5)

    def test_empty_file_has_no_invented_bounds(self):
        report = audit.inspect_gcode(b"")
        self.assertEqual(report["line_count"], 0)
        self.assertEqual(report["explicit_coordinate_bounds_mm_assumed"], {})


class InventoryTests(unittest.TestCase):
    def test_changed_shared_files_and_root_placeholder_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / audit.ROOT_SKETCH).write_bytes(b"")
            for index, folder in enumerate(audit.ORIGINAL_ROOTS):
                firmware = root / folder / audit.FIRMWARE_RELATIVE
                firmware.parent.mkdir(parents=True)
                firmware.write_text(f"#define X_SEPARATION ({350 + 50 * index})\n")
                (root / folder / "main.nc").write_bytes(b"G0 Z5\n")
            report = audit.build_report(root)
            self.assertEqual(report["summary"]["files"], 5)
            self.assertEqual(report["summary"]["identical_shared_files"], 1)
            self.assertEqual(report["summary"]["changed_shared_paths"], [audit.FIRMWARE_RELATIVE])
            self.assertEqual(report["summary"]["root_sketch_bytes"], 0)
            (root / "SdCard" / "main.nc").write_bytes(b"G0 Z0\n")
            self.assertNotEqual(report["manifest"], audit.build_report(root)["manifest"])


if __name__ == "__main__":
    unittest.main()
