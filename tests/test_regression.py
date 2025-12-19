import unittest
import os
import glob
import sys

# Add project root to path so we can import media_utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_utils import get_dialogue_from_ass

class TestSubtitleRegression(unittest.TestCase):
    def test_all_fixtures(self):
        fixtures = glob.glob(os.path.join(os.path.dirname(__file__), "fixtures", "*.ass"))
        for ass_path in fixtures:
            base_name = os.path.splitext(os.path.basename(ass_path))[0]
            expected_path = os.path.join(os.path.dirname(__file__), "expected", f"{base_name}.txt")
            
            with self.subTest(file=base_name):
                print(f"Testing regression for: {base_name}")
                
                # Run the extraction
                events = get_dialogue_from_ass(ass_path)
                
                # Load expected output
                if not os.path.exists(expected_path):
                    self.fail(f"Expected output file not found: {expected_path}")
                
                with open(expected_path, 'r', encoding='utf-8') as f:
                    expected_lines = [line.strip() for line in f if line.strip()]
                
                # Format actual output
                actual_lines = [f"[{e['start']}ms - {e['end']}ms] {e['text']}" for e in events]
                
                # Check line count
                self.assertEqual(len(actual_lines), len(expected_lines), 
                                 f"Line count mismatch for {base_name}. Expected {len(expected_lines)}, got {len(actual_lines)}")
                
                # Check content
                for i, (actual, expected) in enumerate(zip(actual_lines, expected_lines)):
                    self.assertEqual(actual, expected, f"Mismatch in {base_name} at line {i+1}")

if __name__ == '__main__':
    unittest.main()
