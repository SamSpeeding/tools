import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_io import FetchError, image_format, write_json
from catalog_parser import magnet_key, parse_post, parse_resources
from collector import covers, download_image, load_catalogs, sync

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=')


def post(ident, cats):
    return {'id': ident, 'categories': cats, 'tags': [], 'featured_media': 0,
            'title': {'rendered': f'电影《样本{ident}》Test &amp; Name (2025)'},
            'date': '2025-01-01T10:00:00', 'modified': '2025-01-02T10:00:00',
            'link': f'https://example.test/{ident}.html',
            'content': {'rendered': '<p><img src="https://example.test/cover.png"/>◎片　　名　Test &amp; Name<br>◎产　　地　中国大陆<br>◎简　　介<br>简介原文。</p>'}}


class FakeClient:
    def __init__(self, posts):
        self.posts = {p['id']: p for p in posts}
        self.requests = 0
        self.detail_ids = []
        self.api_body_ids = []
        self.failed = set()
        self.image_bytes = PNG
        self.inventory_total = None

    def json(self, url):
        self.requests += 1
        params = parse_qs(urlsplit(url).query)
        if 'include' in params:
            ids = [int(x) for x in params['include'][0].split(',')]
            self.api_body_ids.extend(ids)
            return [copy.deepcopy(self.posts[i]) for i in ids if i in self.posts], {}
        rows = [{'id': i, 'categories': p['categories']} for i, p in sorted(self.posts.items(), reverse=True)]
        page = int(params.get('page', ['1'])[0])
        return rows[(page-1)*100:page*100], {'x-wp-total': str(self.inventory_total if self.inventory_total is not None else len(rows)),
                                           'x-wp-totalpages': str(max(1, (len(rows)+99)//100))}

    def get(self, url):
        self.requests += 1
        if url.endswith('.png'):
            return self.image_bytes, {}
        ident = int(Path(urlsplit(url).path).stem)
        self.detail_ids.append(ident)
        if ident in self.failed:
            raise FetchError('temporary outage', 503)
        digest = f'{ident:040x}'
        return (f'<body class="postid-{ident}"><article class="post-content"><div class="magnet-links"><ul><li>'
                f'<div class="magnet-link-name">Test.2160p.WEB-DL.H265.AAC2.0-GROUP 2.5GB</div>'
                f'<div class="magnet-link-url"><a href="magnet:?xt=urn:btih:{digest}&amp;dn=Test">链接</a></div>'
                '</li></ul></div></article></body>').encode(), {}


class CatalogBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def test_existing_ids_never_fetched_or_modified_and_missing_remote_kept(self):
        c = FakeClient([post(1, [1]), post(2, [3]), post(3, [1, 3])])
        r = sync(self.root, c, workers=2)
        self.assertEqual(r['counts'], {'movie': 2, 'series': 2})
        movie_before = (self.root / 'movies.json').read_bytes()
        series_before = (self.root / 'series.json').read_bytes()
        c.posts.pop(1)
        c.posts[2]['modified'] = '2030-01-01T00:00:00'
        c.posts[2]['title']['rendered'] = 'changed remote title'
        c.detail_ids.clear(); c.api_body_ids.clear()
        r = sync(self.root, c, workers=2)
        self.assertEqual(c.detail_ids, [])
        self.assertEqual(c.api_body_ids, [])
        self.assertEqual((self.root / 'movies.json').read_bytes(), movie_before)
        self.assertEqual((self.root / 'series.json').read_bytes(), series_before)
        self.assertEqual(r['added'], {'movie': 0, 'series': 0})

    def test_deleted_json_rebuilds_only_that_bucket(self):
        c = FakeClient([post(1, [1]), post(2, [3])])
        sync(self.root, c)
        series_before = (self.root / 'series.json').read_bytes()
        (self.root / 'movies.json').unlink()
        c.detail_ids.clear(); c.api_body_ids.clear()
        sync(self.root, c)
        self.assertEqual(c.detail_ids, [1])
        self.assertEqual(c.api_body_ids, [1])
        self.assertEqual((self.root / 'series.json').read_bytes(), series_before)

    def test_failed_detail_is_not_saved_and_retried_next_run(self):
        c = FakeClient([post(1, [1]), post(2, [1])]); c.failed.add(2)
        r = sync(self.root, c)
        self.assertEqual(len(r['failures']), 1)
        self.assertEqual([x['id'] for x in self.read('movies.json')], [1])
        c.failed.clear(); c.detail_ids.clear()
        sync(self.root, c)
        self.assertEqual(c.detail_ids, [2])
        self.assertEqual([x['id'] for x in self.read('movies.json')], [2, 1])

    def test_cover_reuse_even_after_catalog_rebuild_and_index_loss(self):
        c = FakeClient([post(1, [1]), post(2, [3])]); sync(self.root, c)
        r = covers(self.root, c)
        self.assertEqual(r['downloaded'], 1)
        for filename in ('movies.json','series.json'):
            for row in self.read(filename):
                self.assertIn('_'+str(row['id'])+'_',row['cover']['local_path'])
                self.assertTrue((self.root / row['cover']['local_path']).is_file())
        before = c.requests
        self.assertEqual(covers(self.root, c)['skipped'], 1)
        self.assertEqual(c.requests, before)
        (self.root / 'movies.json').unlink()
        (self.root / '.state/images.json').unlink()
        sync(self.root, c)
        before = c.requests
        self.assertEqual(covers(self.root, c)['downloaded'], 0)
        self.assertEqual(c.requests, before)

    def test_bad_image_never_marks_complete(self):
        c = FakeClient([post(1, [1])]); sync(self.root, c)
        c.image_bytes = b'<html>Sorry, unavailable</html>'
        r = covers(self.root, c)
        self.assertEqual(len(r['failures']), 1)
        self.assertFalse(self.read('movies.json')[0]['cover']['downloaded'])

    def test_invalid_json_is_not_replaced(self):
        p = self.root / 'movies.json'; p.write_text('{corrupt')
        c = FakeClient([post(1, [1])])
        with self.assertRaises(ValueError): sync(self.root, c)
        self.assertEqual(c.requests, 0)
        self.assertEqual(p.read_text(), '{corrupt')

    def test_partial_sample_continues_all_older_ids_and_inventory_paging(self):
        c = FakeClient([post(i, [1]) for i in range(1, 103)])
        sync(self.root, c, limit=2)
        self.assertEqual(len(self.read('movies.json')), 2)
        c.detail_ids.clear()
        sync(self.root, c)
        self.assertEqual(len(self.read('movies.json')), 102)
        self.assertEqual(set(c.detail_ids), set(range(1, 101)))

    def test_unstable_inventory_aborts_without_output(self):
        c = FakeClient([post(1, [1])]); c.inventory_total = 2
        with self.assertRaises(FetchError): sync(self.root, c)
        self.assertFalse((self.root / 'movies.json').exists())


class ParserTests(unittest.TestCase):
    def test_entity_decoding_factual_fields_and_missing_values(self):
        r = parse_post(post(1, [1]), 'movie')
        self.assertEqual(r['original_name'], 'Test & Name')
        self.assertEqual(r['countries'], ['中国大陆'])
        self.assertEqual(r['synopsis'], '简介原文。')
        self.assertIsNone(r['duration_minutes'])

    def test_wrong_page_and_challenge_are_not_empty_success(self):
        with self.assertRaises(ValueError): parse_resources('<html>challenge</html>', 1)
        with self.assertRaises(ValueError):
            parse_resources('<body class="postid-2"><article class="post-content"></article></body>', 1)

    def test_btih_hex_and_base32_have_same_identity(self):
        raw = bytes(range(20))
        a = magnet_key('magnet:?xt=urn:btih:' + raw.hex())
        b = magnet_key('magnet:?xt=urn:btih:' + base64.b32encode(raw).decode())
        self.assertEqual(a, b)

    def test_cover_truncation_and_html_rejected(self):
        self.assertEqual(image_format(PNG), 'png')
        self.assertIsNone(image_format(PNG[:-8]))
        self.assertIsNone(image_format(b'<html>not an image</html>'))

    def test_legacy_cover_host_and_moved_upload_path(self):
        class MovedImage:
            calls=[]
            def get(self,url):
                self.calls.append(url)
                if '/2024/11/' in url:
                    raise FetchError('not found',404)
                return PNG,{}
        client=MovedImage()
        data,fmt,resolved=download_image(client,'https://4kbt.net/wp-content/uploads/2024/11/poster.png')
        self.assertEqual(fmt,'png')
        self.assertEqual(resolved,'https://4kbt.org/wp-content/uploads/poster.png')
        self.assertEqual(client.calls,['https://4kbt.org/wp-content/uploads/2024/11/poster.png',resolved])

    def test_legacy_caption_and_synopsis_boundary(self):
        p = post(1, [1])
        p['content']['rendered'] = '<p>◎简<br>真正的简介。<br>磁力链接下载：</p><p>1080P Test BluRay 10GB</p>'
        p['content']['rendered'] += '<p><a href="magnet:?xt=urn:btih:' + 'a'*40 + '">magnet:?xt=urn:btih:' + 'a'*40 + '</a></p>'
        self.assertEqual(parse_post(p, 'movie')['synopsis'], '真正的简介。')
        page = '<article class="post-content">' + p['content']['rendered'] + '</article>'
        resources, _ = parse_resources(page)
        self.assertEqual(resources[0]['resource_name'], '1080P Test BluRay 10GB')

    def test_malformed_source_magnet_is_preserved_with_validation_note(self):
        bad = 'magnet:?xt=urn:btih:' + 'a'*40 + 'WrongSuffix'
        page = '<article class="post-content"><div class="magnet-links"><li><div class="magnet-link-name">原盘91.42G</div><a href="' + bad + '">下载</a></li></div></article>'
        resources, _ = parse_resources(page)
        self.assertEqual(resources[0]['url'], bad)
        self.assertFalse(resources[0]['url_valid'])
        self.assertTrue(resources[0]['validation_error'])

    def test_site_logo_is_not_a_cover(self):
        p = post(1, [1]); p['content']['rendered'] = '<img src="https://4kbt.net/img/logo.png"/>'
        r = parse_post(p, 'movie')
        self.assertIsNone(r['cover']['source_url'])
        self.assertEqual(r['extra_fields']['source_placeholder_image'], 'https://4kbt.net/img/logo.png')

    def test_plain_text_magnet_mixed_with_anchor_is_not_lost(self):
        a='magnet:?xt=urn:btih:'+'a'*40
        b='magnet:?xt=urn:btih:'+'b'*40
        page='<article class="post-content"><p>原盘91.42G<br>'+a+'</p><p>WEB 1080p 2GB<br><a href="'+b+'">'+b+'</a></p></article>'
        rows,_=parse_resources(page)
        self.assertEqual({r['url'] for r in rows},{a,b})
        self.assertEqual(next(r for r in rows if r['url']==a)['resource_name'],'原盘91.42G')

    def test_literal_valid_uri_in_link_text_survives_broken_href(self):
        good='magnet:?xt=urn:btih:'+'a'*40
        bad=good.replace('magnet:', 'magnet')
        page='<article class="post-content"><p>Test.2160p.WEB-DL 10GB<br><a href="'+bad+'">'+good+'</a></p></article>'
        rows,_=parse_resources(page)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url'],good)
        self.assertEqual(rows[0]['source_href'],bad)

    def test_valid_href_keeps_caption_when_display_text_has_trailing_punctuation(self):
        good='magnet:?xt=urn:btih:'+'a'*40
        page='<article class="post-content"><p>Test.2160p.WEB-DL 10GB<br><a href="'+good+'">'+good+'、</a></p></article>'
        rows,_=parse_resources(page)
        self.assertEqual(rows[0]['url'],good)
        self.assertEqual(rows[0]['resource_name'],'Test.2160p.WEB-DL 10GB')

    def test_caption_survives_text_after_anchor(self):
        uri='magnet:?xt=urn:btih:'+'a'*39
        page='<article class="post-content"><p>Test.2160p.BluRay 40GB<br><a href="'+uri+'">'+uri+'</a>5</p></article>'
        rows,_=parse_resources(page)
        self.assertEqual(rows[0]['resource_name'],'Test.2160p.BluRay 40GB')
        self.assertFalse(rows[0]['url_valid'])


if __name__ == '__main__':
    unittest.main()
