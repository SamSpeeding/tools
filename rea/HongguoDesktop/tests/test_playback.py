"""Real encrypted media and HTTP ranges, independent of platform availability."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
import requests
from hongguo_download import media_executable
from mp4_stream import MP4Stream, MediaFormatError
from playback import PlaybackManager, RangeReader, parse_range
from media_fixture import KEY, SPADE, create_fixture, decoded_hashes


class PlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.ffmpeg = media_executable('ffmpeg')
        cls.clear, encrypted, _ = create_fixture(cls.root, cls.ffmpeg, media_executable('ffprobe'))
        cls.encrypted = encrypted.read_bytes()
        cls.requests = []
        data, records = cls.encrypted, cls.requests

        class CDN(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                start, end, _ = parse_range(self.headers.get('Range'), len(data))
                records.append((start, end))
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}' if self.path != '/bad' else 'bytes 0-9/10')
                self.send_header('Content-Length', str(end-start+1))
                self.end_headers()
                self.wfile.write(data[start:end+1])

        cls.cdn = ThreadingHTTPServer(('127.0.0.1', 0), CDN)
        threading.Thread(target=cls.cdn.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.cdn.server_port}/video'

    @classmethod
    def tearDownClass(cls):
        cls.cdn.shutdown()
        cls.cdn.server_close()
        cls.temp.cleanup()

    def track(self):
        return {'main_url': self.url, 'video_meta': {'definition':'1080p', 'size':len(self.encrypted)},
                'encrypt_info':{'encrypt':True,'encryption_method':'cenc-aes-ctr','spade_a':SPADE}}

    def test_range_decryption_matches_independently_encoded_media(self):
        reader = RangeReader([self.url], len(self.encrypted), lambda:None, block_size=1024)
        self.addCleanup(reader.close)
        stream = MP4Stream(reader.read, len(self.encrypted), KEY)
        self.assertLess(reader.received, len(self.encrypted), 'index preparation must not fetch all media')
        # Unaligned ranges, crossing sample/AES/HTTP-block and metadata boundaries.
        chunks = [stream.read_range(start, min(len(self.encrypted)-1, start+1128))
                  for start in range(0, len(self.encrypted), 1129)]
        output = self.root/'streamed.mp4'
        output.write_bytes(b''.join(chunks))
        self.assertEqual(decoded_hashes(self.clear, self.ffmpeg), decoded_hashes(output, self.ffmpeg))
        self.assertEqual(stream.read_range(1019, 2053), output.read_bytes()[1019:2054])
        self.assertLessEqual(len(reader.cache), 8)

    def test_rejects_bad_range_metadata_and_malformed_boxes(self):
        reader = RangeReader([self.url.replace('/video','/bad')], len(self.encrypted), lambda:None)
        self.addCleanup(reader.close)
        with self.assertRaisesRegex(RuntimeError, '字节范围'):
            reader.read(0, 7)
        malformed = b'\0\0\0\4moov' + bytes(24)
        with self.assertRaises(MediaFormatError):
            MP4Stream(lambda a,b:malformed[a:b+1], len(malformed), KEY)
        for value in ('bytes=100-', 'bytes=4-2', 'bytes=-0', 'bytes=0-1,3-4'):
            with self.assertRaises(ValueError):
                parse_range(value, 100)
        self.assertEqual(parse_range('bytes=-12',100), (88,99,True))
        self.assertEqual(parse_range('bytes=12-500',100), (12,99,True))

    def manager(self, gate=None):
        track, calls, events = self.track(), [], []

        class API:
            def models(self, vids, on_source=None):
                calls.append(vids)
                if gate:
                    gate.wait(5)
                source = {'model_api':'video_model', 'model_fallback':True, 'model_fallback_reason':'fixture'}
                if on_source:
                    on_source({**source,'model_api_state':'selected'})
                return {'models':{vids[0]:{'tracks':[track],**source}}}

            def close(self):
                pass

        manager = PlaybackManager(API, ROOT/'vendor', events.append)
        self.addCleanup(manager.shutdown)
        detail = {'series_id':'fixture', 'complete':True,'meta':{'title':'测试'},
                  'episodes':[{'index':i,'vid':str(i)} for i in (1,2)]}
        return manager, detail, calls, events

    def ready(self, manager):
        end = time.monotonic()+10
        while time.monotonic()<end:
            state = manager.snapshot()
            if state and state['status'] in ('ready','failed'):
                self.assertEqual(state['status'],'ready', state)
                return state
            time.sleep(.02)
        self.fail('playback did not finish preparing')

    def test_http_playback_seek_no_resigning_and_close(self):
        manager, detail, calls, events = self.manager()
        self.assertEqual(calls, [])
        initial = manager.start(detail, 1, '1080p')
        state = self.ready(manager)
        self.assertEqual(state['id'], initial['id'])
        url = state['url']
        response = requests.get(url, timeout=5)
        self.assertEqual(response.status_code, 200)
        output = self.root/'http-streamed.mp4'
        output.write_bytes(response.content)
        self.assertEqual(decoded_hashes(self.clear,self.ffmpeg), decoded_hashes(output,self.ffmpeg))
        partial = requests.get(url,headers={'Range':'bytes=1031-5097'},timeout=5)
        self.assertEqual(partial.status_code,206)
        self.assertEqual(partial.content,response.content[1031:5098])
        self.assertEqual(requests.head(url,timeout=5).headers['Content-Length'],str(len(response.content)))
        self.assertEqual(requests.get(url,headers={'Range':'bytes=999999999-'},timeout=5).status_code,416)
        self.assertEqual(calls,[['1']], 'seeks must not fetch another model or signature')
        manager.close('stale-id')
        self.assertEqual(manager.snapshot()['id'],state['id'])
        manager.close(state['id'])
        self.assertEqual(requests.get(url,timeout=5).status_code,404)
        self.assertIsNone(manager.snapshot())

    def test_closed_preparation_cannot_publish_a_stale_session(self):
        gate = threading.Event()
        manager, detail, calls, events = self.manager(gate)
        first = manager.start(detail,1,'1080p')
        manager.close(first['id'])
        second = manager.start(detail,2,'1080p')
        gate.set()
        state = self.ready(manager)
        self.assertEqual(state['id'],second['id'])
        self.assertFalse(any(e['playback']['id']==first['id'] and e['playback']['status']=='ready' for e in events))


if __name__ == '__main__':
    unittest.main()
