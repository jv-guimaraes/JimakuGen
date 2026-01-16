import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import SubtitleJob

class TestRetryLogic(unittest.TestCase):
    def setUp(self):
        self.video_file = "dummy.mkv"
        self.output_path = "dummy.srt"

    @patch('src.core.tempfile.mkdtemp')
    @patch('src.core.Transcriber')
    @patch('src.core.MediaProcessor')
    @patch('src.core.get_dialogue_from_ass')
    @patch('src.core.group_events')
    @patch('src.core.os.makedirs')
    @patch('src.core.shutil.rmtree')
    @patch('src.core.os.remove')
    @patch('src.core.os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_transcription_exception_stops_processing(self, mock_open, mock_exists, mock_remove, mock_rmtree, mock_makedirs, mock_group_events, mock_get_dialogue, MockMedia, MockTranscriber, mock_mkdtemp):
        
        # Setup mocks
        mock_mkdtemp.return_value = "/tmp/dummy"
        mock_media_instance = MockMedia.return_value
        mock_media_instance.get_best_subtitle_track.return_value = {'index': 0, 'score': 100}
        mock_media_instance.get_best_audio_track.return_value = {'index': 1, 'score': 100}
        
        mock_get_dialogue.return_value = [{'start': 0, 'end': 1000, 'text': 'test'}]
        # Return 2 clusters
        mock_group_events.return_value = [[{'start': 0, 'end': 1000, 'text': 'test'}], [{'start': 2000, 'end': 3000, 'text': 'test2'}]]
        mock_exists.return_value = False # Cache does not exist
        
        # Setup Transcriber mock to raise Exception
        mock_transcriber_instance = MockTranscriber.return_value
        mock_transcriber_instance.transcribe_chunk.side_effect = Exception("Model not found")
        
        # Run job
        job = SubtitleJob(self.video_file, output_path=self.output_path)
        job.run()
        
        # Assertions
        # transcribe_chunk should have been called only once
        self.assertEqual(mock_transcriber_instance.transcribe_chunk.call_count, 1)
        self.assertTrue(job.stop_requested)
        
    @patch('src.core.tempfile.mkdtemp')
    @patch('src.core.Transcriber')
    @patch('src.core.MediaProcessor')
    @patch('src.core.get_dialogue_from_ass')
    @patch('src.core.group_events')
    @patch('src.core.os.makedirs')
    @patch('src.core.shutil.rmtree')
    @patch('src.core.validate_chunk')
    @patch('src.core.parse_timestamps')
    @patch('src.core.os.remove')
    @patch('src.core.os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_validation_failure_retries(self, mock_open, mock_exists, mock_remove, mock_parse, mock_validate, mock_rmtree, mock_makedirs, mock_group_events, mock_get_dialogue, MockMedia, MockTranscriber, mock_mkdtemp):
        # Setup mocks
        mock_mkdtemp.return_value = "/tmp/dummy"
        mock_media_instance = MockMedia.return_value
        mock_media_instance.get_best_subtitle_track.return_value = {'index': 0, 'score': 100}
        mock_media_instance.get_best_audio_track.return_value = {'index': 1, 'score': 100}
        
        mock_get_dialogue.return_value = [{'start': 0, 'end': 1000, 'text': 'test'}]
        mock_group_events.return_value = [[{'start': 0, 'end': 1000, 'text': 'test'}]]
        mock_exists.return_value = False # Cache does not exist
        
        mock_transcriber_instance = MockTranscriber.return_value
        mock_transcriber_instance.transcribe_chunk.return_value = "raw text"
        
        mock_parse.return_value = [{'start': 0, 'end': 1000, 'text': 'parsed'}]
        mock_validate.return_value = False # Fail validation
             
        job = SubtitleJob(self.video_file, output_path=self.output_path)
        job.run()
             
        # Should have retried 3 times (MAX_RETRIES)
        self.assertEqual(mock_transcriber_instance.transcribe_chunk.call_count, 3)

if __name__ == '__main__':
    unittest.main()