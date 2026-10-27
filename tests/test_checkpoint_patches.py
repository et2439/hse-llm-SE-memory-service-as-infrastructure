from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.prepare_checkpoints import patch, write_tree


class PatchTests(unittest.TestCase):
    def test_newline_edge_case_and_two_sequential_changes(self):
        base = {"README.md": b"old without newline", "keep.txt": b"keep\n"}
        one = {"README.md": b"KT1\n", "keep.txt": b"keep\n", "data.txt": b"twenty\n"}
        two = {"README.md": b"KT1 and KT2\n", "keep.txt": b"keep\n", "data.txt": b"two hundred\n"}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_tree(folder, base)
            for i, expected in enumerate((one, two)):
                before = base if i == 0 else one
                p = folder.parent / (folder.name + f"-{i}.patch")
                try:
                    p.write_text(patch(before, expected))
                    subprocess.run(["git", "apply", "--check", str(p)], cwd=folder, check=True, capture_output=True)
                    subprocess.run(["git", "apply", str(p)], cwd=folder, check=True, capture_output=True)
                    actual = {f.relative_to(folder).as_posix(): f.read_bytes() for f in folder.rglob("*") if f.is_file()}
                    self.assertEqual(actual, expected)
                finally:
                    p.unlink(missing_ok=True)
