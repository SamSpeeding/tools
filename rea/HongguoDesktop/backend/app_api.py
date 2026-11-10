"""App-only discovery. No public website or downloader-vendor services."""
import re
import uuid
from hongguo_api import HongguoAPI, APIError

RANK_PATH = '/reading/bookapi/bookmall/cell/change/v'
CATEGORY_PATH = '/reading/distribution/category/landpage/v'
RANKS = {
    'all': ('all', ['ranklist_hot_sc', 'ranklist_hot_play_sc', 'ranklist_new_rank_sc']),
    'human': ('human', ['human_hot_sc', 'human_hot_play', 'human_new_rank']),
    'comic': ('comic_series_rank', ['comic_series_hot_rank', 'comic_series_hot_play', 'comic_series_new_rank']),
    'ai': ('ai_playlet', ['ai_playlet_hot_sc', 'ai_playlet_hot_play', 'ai_playlet_new_rank']),
}
GENRES = {'short_play': 'default', 'comic_series': 'comic_series', 'ai_series': 'ai_series'}
DIMENSIONS = {'genre', 'category_dim_theme', 'category_dim_role', 'category_dim_epoch',
              'sort', 'gender', 'creation_status', 'online_time'}


def text(v):
    return re.sub(r'<[^>]+>', '', str(v or '')).strip()


def cover_url(v):
    if isinstance(v, dict):
        return cover_url(v.get('url') or v.get('uri') or v.get('url_list'))
    if isinstance(v, list):
        return next((u for x in v if (u := cover_url(x))), '')
    return v if isinstance(v, str) and v.startswith('https://') else ''


def card(v):
    if not isinstance(v, dict):
        return None
    inner = v.get('video_detail') or {}
    sid = v.get('series_id') or v.get('series_id_str') or inner.get('series_id') or v.get('book_id')
    if not sid or not re.fullmatch(r'\d{10,24}', str(sid)):
        return None
    return {'series_id': str(sid), 'title': text(v.get('title') or v.get('series_title') or
            v.get('name') or inner.get('series_title') or sid),
            'cover': cover_url(v.get('cover') or v.get('series_cover') or inner.get('series_cover')),
            'episode_cnt': v.get('episode_cnt') or inner.get('episode_cnt') or 0,
            'score': text(v.get('score') or inner.get('score')),
            'intro': text(v.get('video_desc') or v.get('series_intro') or inner.get('series_intro')),
            'status': text(v.get('series_status')), 'source_type': v.get('source_type', '')}


def unique_cards(videos):
    seen, out = set(), []
    for v in videos:
        item = card(v)
        if item and item['series_id'] not in seen:
            seen.add(item['series_id'])
            out.append(item)
    return out


def more(v):
    return v in (True, 1, '1', 'true')


class AppAPI(HongguoAPI):
    def search_page(self, query, cursor=None):
        r = self.search(query, cursor=cursor)
        return {'items': [{k: v for k, v in x.items() if k != 'raw'} for x in r['items']],
                'has_more': r['has_more'], 'next_cursor': r['next_cursor'], 'warnings': r['warnings']}

    def rank_page(self, category='all', board='hot', cursor=None):
        if category not in RANKS or board not in ('recommend', 'hot', 'new'):
            raise ValueError('无效榜单类型')
        selected, boards = RANKS[category]
        offset = int((cursor or {}).get('offset', 0))
        q = {'cell_id': '7470092475068071998', 'tab_type': '26', 'client_req_type': '2',
             'client_template': '2', 'screen_width_px': '1350', 'session_uuid': str(uuid.uuid4()),
             'selected_items': selected, 'sub_selected_items': boards[('recommend', 'hot', 'new').index(board)]}
        if offset:
            q['offset'] = str(offset)
        r = self._api_once('GET', RANK_PATH, extra_query=q)
        data = r.get('data', {}).get('cell_view', {})
        if not isinstance(data, dict) or not isinstance(data.get('cell_data'), list):
            raise APIError('榜单返回结构不完整', response=r)
        videos = []
        for c in data['cell_data']:
            v = c.get('video_data', []) if isinstance(c, dict) else []
            videos.extend(v if isinstance(v, list) else [v])
        nxt = data.get('next_offset')
        has_more = more(data.get('has_more')) and nxt is not None and str(nxt) != str(offset)
        return {'items': unique_cards(videos), 'has_more': has_more,
                'next_cursor': {'offset': nxt} if has_more else None}

    def category(self, genre='short_play', selections=None, cursor=None, panel=False, latest=False):
        if genre not in GENRES:
            raise ValueError('无效内容类型')
        offset = int((cursor or {}).get('offset', 0))
        selected = {k: [] for k in DIMENSIONS}
        for k, values in (selections or {}).items():
            if k in DIMENSIONS and k != 'genre' and isinstance(values, list):
                selected[k] = [str(x) for x in values][:30]
        selected['genre'] = [genre]
        if not selected['sort']:
            selected['sort'] = ['online_time']
        if latest:
            selected = {k: [] for k in DIMENSIONS}
            selected.update(genre=[genre], sort=['online_time'])
        if panel:
            selected = {k: [] for k in DIMENSIONS if k != 'creation_status'}
            selected['genre'] = [genre]
        body = {'filter_ids': '', 'req_scene': GENRES[genre], 'offset': offset,
                'need_selector_panel': panel, 'limit': 1 if panel else 18,
                'select_items': selected, 'session_id': '',
                'req_type': 'default' if panel else 'only_content', 'client_req_type': 3}
        r = self._api_once('POST', CATEGORY_PATH, body=body)
        data = r.get('data')
        if not isinstance(data, dict):
            raise APIError('分类返回结构不完整', response=r)
        if panel:
            rows = data.get('selector_rows')
            if not isinstance(rows, list):
                raise APIError('未取得平台分类选项', response=r)
            return {'rows': rows}
        videos = data.get('video_data')
        if not isinstance(videos, list):
            raise APIError('未取得平台剧目列表', response=r)
        has_more = more(data.get('has_more')) and bool(videos)
        return {'items': unique_cards(videos), 'has_more': has_more,
                'next_cursor': {'offset': offset + len(videos)} if has_more else None,
                'raw_count': len(videos)}
