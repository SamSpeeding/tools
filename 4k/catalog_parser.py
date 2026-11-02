"""Parse public WordPress records and resource modules, without executing page code."""
from __future__ import annotations

import base64
import hashlib
import html
import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

SITE = 'https://4kbt.org'
TZ = timezone(timedelta(hours=8))
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
BLOCK = set('p div li h1 h2 h3 h4 h5 h6 tr section article blockquote'.split())


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()

    def text(self):
        if self.tag in ('script', 'style', 'noscript'):
            return ''
        if self.tag == 'br':
            return '\n'
        text = ''.join(c.text() if isinstance(c, Node) else c for c in self.children)
        return '\n' + text + '\n' if self.tag in BLOCK else text

    def text_without_links(self):
        if self.tag in ('a', 'script', 'style', 'noscript'):
            return ''
        if self.tag == 'br':
            return '\n'
        text = ''.join(c.text_without_links() if isinstance(c, Node) else c for c in self.children)
        return '\n' + text + '\n' if self.tag in BLOCK else text


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(value):
    return ' '.join(html.unescape(str(value or '')).split())


def unique(values):
    return list(dict.fromkeys(x for x in values if x))


def split_values(value):
    return unique(clean(v) for v in re.split(r'\n|\s*/\s*|[；;、]', value or ''))


def site_time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)).isoformat(timespec='seconds')


def first_number(value):
    match = re.search(r'\d+', value or '')
    return int(match[0]) if match else None


def fields_from_body(text):
    fields, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r'^(?:磁力链接下载|磁力下载|下载地址|下载链接|资源下载)\s*[：:]?', line):
            break
        if line.startswith('magnet:?'):
            break
        # A few source articles have a truncated heading: “◎简” instead of “◎简介”.
        line = re.sub(r'^([◎●])\s*简(?=\s|$)', r'\1简介', line) if not re.match(r'^[◎●]\s*简\s*介', line) else line
        if line.startswith(('◎', '●')):
            # Labels use ideographic padding, sometimes with ASCII spaces between characters.
            marker = re.match(r'^[◎●]\s*(.*?)(?:[\u3000 \t]{2,}|[：:])(.*)$', line)
            if marker:
                key = re.sub(r'\s+', '', marker[1])
                value = marker[2].strip()
                # A padded label may have been split before its final characters.
                compact = re.sub(r'\s+', '', line[1:])
                known = next((k for k in FIELD_NAMES if compact.startswith(k)), None)
                if known:
                    pattern = r'^\s*' + r'\s*'.join(map(re.escape, known)) + r'\s*[：:]?\s*'
                    value = re.sub(pattern, '', line[1:], count=1, flags=re.I)
                    key = known
            else:
                compact = re.sub(r'\s+', '', line[1:])
                key = next((k for k in FIELD_NAMES if compact.startswith(k)), compact)
                pattern = r'^\s*' + r'\s*'.join(map(re.escape, key)) + r'\s*[：:]?\s*'
                value = re.sub(pattern, '', line[1:], count=1, flags=re.I)
            current = key
            fields.setdefault(key, [])
            if value:
                fields[key].append(value)
        elif current:
            fields[current].append(line)
        else:
            for key in FIELD_NAMES:
                match = re.match(r'^' + r'\s*'.join(map(re.escape, key)) + r'\s*[：:]\s*(.*)$', line, re.I)
                if match:
                    current = key
                    fields.setdefault(key, []).append(match[1])
                    break
    return {k: '\n'.join(v).strip() for k, v in fields.items()}


FIELD_NAMES = sorted([
    'IMDb评分', 'IMDB评分', 'IMDb链接', 'IMDB链接', '豆瓣评分', '豆瓣链接',
    '上映日期', '首播日期', '获奖情况', '译名', '片名', '标题', '年代', '年份',
    '产地', '国家', '地区', '类别', '类型', '语言', '集数', '片长', '导演',
    '编剧', '主演', '演员', '简介', '首播', '又名', '制片国家/地区', '标签',
    '文件格式', '视频尺寸', '文件大小', '压制小组',
], key=len, reverse=True)


def cover_filename(kind, post_id, name, url, fmt=None):
    stem = re.sub(r'[\s/\\:*?"<>|\x00-\x1f]+', '_', name).strip('._') or '未命名'
    stem = stem.encode('utf-8')[:96].decode('utf-8', errors='ignore')
    ext = (fmt or urlsplit(url).path.rsplit('.', 1)[-1]).lower()
    if ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif', 'avif'):
        ext = 'img'
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f'img/{kind}_{post_id}_{stem}_{digest}.{ext}'


def external_source(name, fields, body):
    pattern = r'imdb\.com/title/(tt\d+)' if name == 'imdb' else r'douban\.com/subject/(\d+)'
    match = re.search(pattern, body, re.I)
    ident = match[1] if match else None
    prefix = 'IMDb' if name == 'imdb' else '豆瓣'
    rating_text = fields.get(prefix + '评分', fields.get(prefix.upper() + '评分', ''))
    score = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', rating_text)
    if not score:
        score = re.search(r'^\s*(\d+(?:\.\d+)?)', rating_text)
    votes = re.search(r'(?:from\s+)([\d,]+)', rating_text, re.I)
    if not votes:
        votes = re.search(r'([\d,]+)\s*(?:人|users|votes)', rating_text, re.I)
    return {
        'id': ident,
        'url': (f'https://www.imdb.com/title/{ident}/' if name == 'imdb'
                else f'https://movie.douban.com/subject/{ident}/') if ident else None,
        'rating': float(score[1]) if score else None,
        'rating_max': 10,
        'vote_count': int(votes[1].replace(',', '')) if votes else None,
    }


def parse_post(post, kind):
    title = clean(post['title']['rendered'])
    body = post.get('content', {}).get('rendered', '')
    doc = Document(body)
    text = doc.root.text().strip()
    fields = fields_from_body(text)
    title_name = re.search(r'《([^》]+)》', title)
    translations = split_values(fields.get('译名', ''))
    name = fields.get('标题') or (title_name[1] if title_name else None)
    if not name:
        name = next((n for n in translations if re.search(r'[\u4e00-\u9fff]', n)), None)
    name = clean(name or fields.get('片名') or title)
    original = clean(fields.get('片名')) or None
    year = first_number(fields.get('年代', fields.get('年份', '')))
    if not year:
        years = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', title)
        year = int(years[-1]) if years else None
    terms = [t for group in post.get('_embedded', {}).get('wp:term', [])
             for t in group if isinstance(t, dict)]
    categories = [dict(id=t['id'], name=clean(t.get('name')), slug=t.get('slug'))
                  for t in terms if t.get('taxonomy') == 'category']
    tags = [dict(id=t['id'], name=clean(t.get('name')), slug=t.get('slug'))
            for t in terms if t.get('taxonomy') == 'post_tag']
    if not categories:
        categories = [{'id': i, 'name': {1: '4K电影', 3: '4K剧集'}.get(i), 'slug': None}
                      for i in post.get('categories', [])]
    if not tags:
        tags = [{'id': i, 'name': None, 'slug': None} for i in post.get('tags', [])]
    media = next((m for m in post.get('_embedded', {}).get('wp:featuredmedia', [])
                  if m.get('source_url')), {})
    img = next((n for n in doc.root.walk() if n.tag == 'img' and n.attrs.get('src')), None)
    url = media.get('source_url') or (urljoin(SITE, img.attrs['src']) if img else None)
    placeholder_image = None
    if not media.get('source_url') and url and re.search(r'/logo\.(?:png|jpg|webp|svg)$', urlsplit(url).path, re.I):
        placeholder_image, url = url, None
    details = media.get('media_details', {})
    dates = []
    for date, region in re.findall(r'(\d{4}-\d{2}-\d{2})(?:\s*[（(]([^）)]+)[）)])?',
                                   fields.get('上映日期', fields.get('首播日期', fields.get('首播', '')))):
        dates.append({'date': date, 'region': region or None, 'raw': date + (f'({region})' if region else '')})
    season = re.search(r'(?:Season\s*|\bS)(\d+)', title, re.I) if kind == 'series' else None
    season_zh = re.search(r'第([一二三四五六七八九十百\d]+)季', name) if kind == 'series' else None
    season_number = int(season[1]) if season else None
    if season_number is None and season_zh:
        season_number = chinese_number(season_zh[1])
    runtime = first_number(fields.get('片长'))
    synopsis = fields.get('简介') or (text if not fields else '')
    recognized = set(FIELD_NAMES) - {'获奖情况', '标签', '文件格式', '视频尺寸', '文件大小', '压制小组'}
    return {
        'id': post['id'], 'type': kind, 'title': title, 'name': name,
        'original_name': original,
        'aliases': unique(x for x in translations + split_values(fields.get('又名')) if x not in (name, original)),
        'original_url': post.get('link', f'{SITE}/{post["id"]}.html'),
        'api_url': f'{SITE}/wp-json/wp/v2/posts/{post["id"]}',
        'year': year, 'countries': split_values(fields.get('产地', fields.get('国家', fields.get('地区', '')))),
        'genres': split_values(fields.get('类别', fields.get('类型', ''))),
        'languages': split_values(fields.get('语言')),
        'release_dates': dates, 'season_number': season_number,
        'episode_count': first_number(fields.get('集数')),
        'duration_minutes': runtime, 'duration_scope': ('episode' if kind == 'series' else 'movie') if runtime else None,
        'directors': split_values(fields.get('导演')), 'writers': split_values(fields.get('编剧')),
        'cast': split_values(fields.get('主演', fields.get('演员', ''))),
        'synopsis': synopsis, 'synopsis_kind': 'source',
        'external_sources': {k: external_source(k, fields, body) for k in ('imdb', 'douban')},
        'categories': categories, 'tags': tags,
        'cover': {
            'media_id': post.get('featured_media') or None, 'source_url': url,
            'width': details.get('width') or (first_number(img.attrs.get('width')) if img else None),
            'height': details.get('height') or (first_number(img.attrs.get('height')) if img else None),
            'format': (media.get('mime_type') or '').replace('image/', '') or (urlsplit(url).path.rsplit('.', 1)[-1].lower() if url else None),
            'alt_text': media.get('alt_text', img.attrs.get('alt', '') if img else ''),
            'local_path': cover_filename(kind, post['id'], name, url) if url else None,
            'downloaded': False,
        },
        'magnet_links': [], 'extra_links': [], 'source_fields': fields,
        'extra_fields': dict({k: v for k, v in fields.items() if k not in recognized},
                             **({'source_placeholder_image': placeholder_image} if placeholder_image else {})),
        'published_at': site_time(post.get('date')), 'source_modified_at': site_time(post.get('modified')),
        'sync': {}, 'source_notes': ['正文图片是网站标志占位图，没有可用封面。'] if placeholder_image else [],
    }


def chinese_number(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip('零一二三四五六七八九', range(10)))
    if '十' in value:
        before, after = value.split('十', 1)
        return (digits.get(before, 1) * 10 + digits.get(after, 0)) if '百' not in value else None
    return digits.get(value)


def magnet_key(url):
    if not url.lower().startswith('magnet:?'):
        raise ValueError('不是磁力 URI')
    for xt in parse_qs(urlsplit(url).query).get('xt', []):
        if xt.lower().startswith('urn:btih:'):
            digest = xt[9:]
            if re.fullmatch(r'[a-fA-F0-9]{40}', digest):
                return 'btih:' + digest.lower()
            if re.fullmatch(r'[A-Z2-7a-z]{32}', digest):
                return 'btih:' + base64.b32decode(digest.upper()).hex()
        if re.fullmatch(r'urn:btmh:1220[0-9a-fA-F]{64}', xt):
            return 'btmh:' + xt[9:].lower()
    raise ValueError('磁力 URI 缺少有效 BTIH/BTMH')


def parse_resource(name, url):
    def match(pattern):
        m = re.search(pattern, name, re.I)
        return m[0] if m else None
    size = match(r'\d+(?:\.\d+)?\s*(?:TiB|GiB|MiB|TB|GB|MB)\b')
    resolution = match(r'\b(?:2160|1080|720|480)[pi]\b')
    codec = match(r'HEVC|AVC|H[. ]?26[45]|x26[45]|AV1|VC[. -]?1|MPEG[. -]?2')
    if codec and re.fullmatch(r'H[. ]?26[45]', codec, re.I):
        codec = 'H.' + re.sub(r'\D', '', codec)
    source = match(r'WEB[. -]?DL|WEBRip|Blu[. -]?Ray|BDRip|BDREMUX|HDTV')
    dynamic = match(r'HDR10\+?|Dolby[. ]?Vision|\bDoVi\b|\bDV\b|HDR|EDR')
    audio_codec = match(r'TrueHD|DTS[. -]?HD[. -]?MA|DTS[. -]?HD|DTS[. -]?X|DDP|E[. -]?AC[. -]?3|AC[. -]?3|DTS|AAC|FLAC|PCM|DD(?=\d)')
    channels = None
    if audio_codec:
        tail = name[name.lower().find(audio_codec.lower()) + len(audio_codec):]
        ch = re.match(r'[. _-]*(\d[.]\d)', tail)
        channels = ch[1] if ch else None
    labels = unique(re.findall(r'(?:简繁英字幕|简繁字幕|简英字幕|繁英字幕|中文字幕|中字|内嵌字幕|外挂字幕)', name))
    langs = unique(re.findall(r'(?:国语配音|粤语配音|英语配音|国粤双语|多国语言|国语|粤语)', name))
    group = re.search(r'-([A-Za-z][A-Za-z0-9]*)(?=\s|[【\[]|$)', name)
    try:
        identity, validation_error = magnet_key(url), None
    except ValueError as exc:
        identity, validation_error = 'raw:' + hashlib.sha256(url.encode()).hexdigest(), str(exc)
    return {
        'resource_name': name or None, 'url': url, 'identity': identity,
        'url_valid': validation_error is None, 'validation_error': validation_error,
        'size_text': size, 'size_bytes': None,
        'video': {'resolution': resolution, 'source': source, 'codec': codec,
                  'dynamic_range_label': dynamic, 'quality_labels': unique(re.findall(r'REMUX|高码版|\bHQ\b|REPACK', name, re.I))},
        'audio': [{'codec': audio_codec, 'channels': channels, 'language_label': '/'.join(langs) or None,
                   'atmos': True if re.search('Atmos', name, re.I) else None}] if audio_codec or langs else [],
        'subtitle_labels': labels, 'release_group': group[1] if group else None,
        'present_on_source': True,
    }


def parse_resources(source, expected_id=None):
    doc = Document(source)
    article = next((n for n in doc.root.walk() if n.has_class('post-content')), None)
    if article is None:
        raise ValueError('详情页缺少正文结构，保留旧数据并等待重试')
    # Never accept a soft-404 or a different post returned by a redirect.
    body = next((n for n in doc.root.walk() if n.tag == 'body'), None)
    if expected_id and body:
        ids = re.findall(r'\bpostid-(\d+)\b', body.attrs.get('class', ''))
        if ids and str(expected_id) not in ids:
            raise ValueError('详情页 ID 与请求不一致')
    results, extras, seen = [], [], set()
    # Legacy pages often place a resource caption and the URI in adjacent paragraphs.
    legacy_names = {}
    previous = ''
    for line in article.text().splitlines():
        line = line.strip()
        if not line:
            continue
        for found in re.finditer(r'magnet:\?[^\s<>\"\']+', line, re.I):
            caption = line[:found.start()].strip() or previous
            if len(caption) < 600 and re.search(r'\d{3,4}[pPiI]|\d+(?:\.\d+)?\s*[GMT](?:i?B)?|BluRay|WEB[.-]DL|REMUX|蓝光|原盘|\b4K\b|\b3D\b', caption, re.I):
                try:
                    legacy_names[magnet_key(found[0])] = caption
                except ValueError:
                    legacy_names['raw:' + hashlib.sha256(found[0].encode()).hexdigest()] = caption
        if 'magnet:?' not in line:
            previous = line
    for node in article.walk():
        if node.tag != 'a':
            continue
        url = html.unescape(node.attrs.get('href', '')).strip()
        source_href = url
        visible_uri = re.search(r'magnet:\?[^\s<>\"\']+', node.text(), re.I)
        # A few old posts have a broken href but print a complete, valid URI as the link text.
        if visible_uri:
            try:
                magnet_key(url)
            except ValueError:
                try:
                    magnet_key(visible_uri[0])
                    url = visible_uri[0]
                except ValueError:
                    pass
        if url.lower().startswith('magnet:?'):
            try:
                key = magnet_key(url)
            except ValueError:
                key = 'raw:' + hashlib.sha256(url.encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            parent = node.parent
            label = ''
            while parent and parent is not article:
                name_node = next((n for n in parent.walk() if n.has_class('magnet-link-name')), None)
                if name_node:
                    label = clean(name_node.text())
                    break
                if parent.tag == 'p' and node.text().strip():
                    before = parent.text().split(node.text(), 1)[0]
                    preceding = [line.strip() for line in before.splitlines() if line.strip()]
                    candidate = preceding[-1] if preceding else ''
                    if len(candidate) < 600 and re.search(r'\d{3,4}[pPiI]|\d+(?:\.\d+)?\s*[GMT](?:i?B)?|BluRay|WEB[.-]DL|REMUX|蓝光|原盘|\b4K\b|\b3D\b', candidate, re.I):
                        label = candidate
                        break
                if parent.tag == 'li':
                    label = clean(parent.text().replace(node.text(), ''))
                    break
                parent = parent.parent
            if not label:
                label = legacy_names.get(key)
                if not label and visible_uri:
                    try:
                        visible_key = magnet_key(visible_uri[0])
                    except ValueError:
                        visible_key = 'raw:' + hashlib.sha256(visible_uri[0].encode()).hexdigest()
                    label = legacy_names.get(visible_key)
                label = label or clean(node.text())
                if label.lower().startswith('magnet:'):
                    label = parse_qs(urlsplit(url).query).get('dn', [''])[0]
            resource = parse_resource(label, url)
            if source_href != url:
                resource['source_href'] = source_href
            results.append(resource)
        elif url.startswith(('https://', 'http://')):
            if any(x in url for x in ('pan.baidu.com', 'aliyundrive.com', 'alipan.com', 'pan.quark.cn',
                                      '115.com', 'drive.google.com', 'subhd.', 'zimuku.')):
                extras.append({'name': clean(node.text()), 'url': url})
    # Some posts print the URI as plain text without an <a> element.
    for match in re.finditer(r'magnet:\?[^\s<>\"\']+', article.text_without_links(), re.I):
        url = html.unescape(match[0]).strip()
        try:
            key = magnet_key(url)
        except ValueError:
            key = 'raw:' + hashlib.sha256(url.encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            results.append(parse_resource(legacy_names.get(key, ''), url))
    return results, extras
