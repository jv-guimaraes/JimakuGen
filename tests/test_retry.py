import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import process_video

class TestRetryLogic(unittest.TestCase):
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.core.Transcriber')
    @patch('src.core.get_best_english_track')
    @patch('src.core.get_best_japanese_audio_track')
    @patch('src.core.subprocess.run')
    @patch('src.core.get_dialogue_from_ass')
    @patch('src.core.group_events')
    @patch('src.core.os.makedirs')
    @patch('src.core.shutil.rmtree')
    @patch('src.core.os.remove')
    @patch('src.core.os.path.exists')
    def test_transcription_exception_stops_processing(self, mock_exists, mock_remove, mock_rmtree, mock_makedirs, mock_group_events, mock_get_dialogue, mock_subprocess, mock_get_jp_audio, mock_get_eng_track, MockTranscriber, mock_open):
        
        # Setup mocks
        mock_get_eng_track.return_value = {'index': 0, 'score': 100, 'frames': 100}
        mock_get_jp_audio.return_value = {'index': 1, 'score': 100}
        mock_get_dialogue.return_value = [{'start': 0, 'end': 1000, 'text': 'test'}]
        # Return 2 clusters to verify we stop after the first failure and don't process the second
        mock_group_events.return_value = [[{'start': 0, 'end': 1000, 'text': 'test'}], [{'start': 2000, 'end': 3000, 'text': 'test2'}]]
        mock_exists.return_value = False # Cache does not exist
        
        # Setup Transcriber mock to raise Exception
        mock_instance = MockTranscriber.return_value
        mock_instance.transcribe_chunk.side_effect = Exception("Model not found")
        
        # Run process_video
        process_video("dummy.mkv", output_path="dummy.srt")
        
        # Assertions
        # transcribe_chunk should have been called only once (because we stop on critical error)
        self.assertEqual(mock_instance.transcribe_chunk.call_count, 1)
        
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.core.Transcriber')
    @patch('src.core.get_best_english_track')
    @patch('src.core.get_best_japanese_audio_track')
    @patch('src.core.subprocess.run')
    @patch('src.core.get_dialogue_from_ass')
    @patch('src.core.group_events')
    @patch('src.core.os.makedirs')
    @patch('src.core.shutil.rmtree')
    @patch('src.core.validate_chunk')
    @patch('src.core.parse_timestamps')
    @patch('src.core.os.remove')
    @patch('src.core.os.path.exists')
    def test_validation_failure_retries(self, mock_exists, mock_remove, mock_parse, mock_validate, mock_rmtree, mock_makedirs, mock_group_events, mock_get_dialogue, mock_subprocess, mock_get_jp_audio, mock_get_eng_track, MockTranscriber, mock_open):
        # Setup mocks for validation failure case
        mock_get_eng_track.return_value = {'index': 0, 'score': 100, 'frames': 100}
        mock_get_jp_audio.return_value = {'index': 1, 'score': 100}
        mock_get_dialogue.return_value = [{'start': 0, 'end': 1000, 'text': 'test'}]
        mock_group_events.return_value = [[{'start': 0, 'end': 1000, 'text': 'test'}]]
        mock_exists.return_value = False # Cache does not exist
        
        mock_instance = MockTranscriber.return_value
        mock_instance.transcribe_chunk.return_value = "raw text"
        
        mock_parse.return_value = [{'start': 0, 'end': 1000, 'text': 'parsed'}]
        mock_validate.return_value = False # Fail validation
             
        process_video("dummy.mkv", output_path="dummy.srt")
             
        # Should have retried 3 times (initial + 2 retries = 3 calls? No, loop runs while retries < 3)
        # Attempt 1: retries=0. Fail. retries=1.
        # Attempt 2: retries=1. Fail. retries=2.
        # Attempt 3: retries=2. Fail. retries=3.
        # Loop terminates. Total 3 calls.
        self.assertEqual(mock_instance.transcribe_chunk.call_count, 3)

if __name__ == '__main__':
    unittest.main()
