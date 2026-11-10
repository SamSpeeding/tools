import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hongguo_download as download


class SelectionTests(unittest.TestCase):
    def test_ranges_and_deduplication_follow_episode_numbers(self):
        self.assertEqual(download.parse_episodes('1，3-5,3', range(1, 7)), [1, 3, 4, 5])
        self.assertEqual(download.parse_episodes('all', [2, 4, 6]), [2, 4, 6])
        self.assertEqual(download.parse_episodes('', [1]), [])

    def test_invalid_or_missing_episode_numbers_are_rejected(self):
        for value in ('0', '-1', '3-2', '1,,2', '1-1000000000', 'all,1', '1-3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                download.parse_episodes(value, [1, 3, 4])

    def test_requested_quality_does_not_silently_change(self):
        model = {'tracks': [{'backup_url': 'https://backup.test/video',
                             'video_meta': {'definition': '720p'}}]}
        self.assertEqual(download.choose_track(model, '720p'), model['tracks'][0])
        with self.assertRaisesRegex(RuntimeError, '1080p'):
            download.choose_track(model, '1080p')


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.detail = {'series_id': 's1', 'meta': {'title': '测试'},
                       'episodes': [{'index': i, 'vid': f'v{i}'} for i in (1, 2)]}
        self.api = Mock()
        self.api.models.side_effect = lambda vids: {'models': {v: {'tracks': [
            {'main_url': 'https://cdn.test/' + v, 'video_meta': {'definition': '1080p'}}]} for v in vids}}
        self.addCleanup(patch.stopall)
        patch.object(download, 'preflight').start()
        patch.object(download, 'fetch_track', side_effect=lambda session, track, path, timeout: path.write_bytes(b'encrypted')).start()
        patch.object(download.time, 'sleep').start()

    @staticmethod
    def playable(source, track, target, vendor):
        target.write_bytes(b'validated media')
        return {'full_decode_validated': True}

    def run_download(self, selected):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return download.download_selected(self.api, self.detail, selected, self.directory)

    def test_only_selected_episodes_are_queried_and_verified_files_skip(self):
        with patch.object(download, 'playable_file', side_effect=self.playable):
            self.assertEqual(self.run_download([2]), 0)
            self.assertEqual(self.api.models.call_args.args[0], ['v2'])
            self.api.reset_mock()
            self.assertEqual(self.run_download([2]), 0)
            self.api.models.assert_not_called()
        self.assertEqual(len(list(self.directory.rglob('*.mp4'))), 1)

    def test_failed_validation_publishes_no_mp4_and_continues_other_episodes(self):
        def convert(source, track, target, vendor):
            if track['main_url'].endswith('v1'):
                target.write_bytes(b'invalid')
                raise RuntimeError('decode failed')
            return self.playable(source, track, target, vendor)
        with patch.object(download, 'playable_file', side_effect=convert):
            self.assertEqual(self.run_download([1, 2]), 2)
        files = list(self.directory.rglob('*.mp4'))
        self.assertEqual([p.name for p in files], ['第002集_1080p.mp4'])
        report = json.loads(next(self.directory.rglob('下载记录.json')).read_text())
        self.assertEqual([e['status'] for e in report['episodes']], ['failed', 'complete'])
        self.assertEqual(report['status'], 'partial')

    def test_retry_refreshes_model_before_downloading_again(self):
        models = [{'models': {'v1': {'tracks': [{'main_url': 'https://cdn.test/' + token,
                   'video_meta': {'definition': '1080p'}}]}}} for token in ('expired', 'fresh')]
        self.api.models.side_effect = models
        with patch.object(download, 'fetch_track', side_effect=[RuntimeError('expired'), None]) as fetch:
            with patch.object(download, 'playable_file', side_effect=self.playable):
                self.assertEqual(self.run_download([1]), 0)
        self.assertEqual(fetch.call_args_list[1].args[1]['main_url'], 'https://cdn.test/fresh')

    def test_interrupt_preserves_report_and_removes_partial_temp_file(self):
        with patch.object(download, 'playable_file', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_download([1, 2])
        report = json.loads(next(self.directory.rglob('下载记录.json')).read_text())
        self.assertEqual(report['status'], 'interrupted')
        self.assertEqual(report['episodes'][0]['status'], 'interrupted')
        self.assertEqual(list(self.directory.rglob('*.mp4')), [])

    def test_existing_unverified_file_is_never_overwritten(self):
        folder = self.directory/'测试_s1'
        folder.mkdir()
        target = folder/'第001集_1080p.mp4'
        target.write_bytes(b'user file')
        self.assertEqual(self.run_download([1]), 2)
        self.assertEqual(target.read_bytes(), b'user file')
        self.api.models.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_hash_mismatch_tries_backup_and_never_accepts_corrupt_download(self):
        payload = b'valid media'
        track = {'main_url': 'https://cdn.test/main', 'backup_url': 'https://cdn.test/backup',
                 'video_meta': {'size': len(payload), 'file_hash': hashlib.md5(payload).hexdigest()}}
        responses = []
        for content in (b'bad', payload):
            response = Mock(status_code=200)
            response.iter_content.return_value = [content]
            responses.append(contextlib.nullcontext(response))
        session = Mock()
        session.get.side_effect = responses
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            target = Path(folder)/'source.mp4'
            download.fetch_track(session, track, target, 10)
            self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(session.get.call_count, 2)


if __name__ == '__main__':
    unittest.main()
