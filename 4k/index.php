<?php
declare(strict_types=1);

// Deploy this file beside movies.json and series.json. No build step or database.
const PAGE_SIZE = 24;
const CATALOGS = ['movie' => 'movies.json', 'series' => 'series.json'];

header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin');
header('Cache-Control: no-cache');

function esc($value): string
{
    return htmlspecialchars((string) ($value ?? ''), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function param(string $key, string $default = ''): string
{
    return isset($_GET[$key]) && is_string($_GET[$key]) ? trim($_GET[$key]) : $default;
}

function lower(string $text): string
{
    return function_exists('mb_strtolower') ? mb_strtolower($text, 'UTF-8') : strtolower($text);
}

function strings($values): array
{
    if (!is_array($values)) {
        return [];
    }
    return array_values(array_filter($values, static fn($v) => is_string($v) && trim($v) !== ''));
}

function webUrl($url): string
{
    return is_string($url) && filter_var($url, FILTER_VALIDATE_URL)
        && in_array(strtolower((string) parse_url($url, PHP_URL_SCHEME)), ['http', 'https'], true)
        ? $url : '';
}

function coverUrl(array $record): string
{
    $cover = $record['cover'] ?? [];
    $url = webUrl($cover['download_url'] ?? '') ?: webUrl($cover['source_url'] ?? '');
    return $url;
}

function entryName(array $record): string
{
    return (string) (($record['name'] ?? '') ?: (($record['original_name'] ?? '') ?: ($record['title'] ?? '未命名条目')));
}

function catalogUrl(string $type, string $query = '', int $page = 1, ?int $item = null): string
{
    $args = ['type' => $type];
    if ($query !== '') $args['q'] = $query;
    if ($page > 1) $args['page'] = $page;
    if ($item !== null) $args['item'] = $item;
    return '?' . http_build_query($args, '', '&', PHP_QUERY_RFC3986);
}

function readCatalog(string $type): array
{
    $file = __DIR__ . '/' . CATALOGS[$type];
    if (!is_file($file) || !is_readable($file)) {
        throw new RuntimeException('无法读取 ' . CATALOGS[$type] . '，请将它放在 index.php 同一目录，并允许 PHP 读取。');
    }
    $raw = file_get_contents($file);
    if ($raw === false) throw new RuntimeException('目录读取失败，请稍后重试。');
    try {
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException $e) {
        throw new RuntimeException(CATALOGS[$type] . ' 格式有误，请检查 JSON 后刷新。');
    }
    if (!is_array($data) || !array_is_list($data) || !str_starts_with(ltrim($raw), '[')) {
        throw new RuntimeException(CATALOGS[$type] . ' 的顶层必须是数组。');
    }
    unset($raw);
    foreach ($data as $record) {
        if (!is_array($record) || !isset($record['id']) || !is_numeric($record['id'])) {
            throw new RuntimeException(CATALOGS[$type] . ' 中有缺少有效 ID 的条目。');
        }
    }
    return $data;
}

function matches(array $record, array $words): bool
{
    $fields = [$record['name'] ?? '', $record['original_name'] ?? '', $record['title'] ?? ''];
    foreach (['aliases', 'directors', 'cast', 'genres'] as $key) {
        array_push($fields, ...strings($record[$key] ?? []));
    }
    foreach (($record['tags'] ?? []) as $tag) {
        if (is_array($tag) && is_string($tag['name'] ?? null)) $fields[] = $tag['name'];
    }
    $haystack = lower(implode(' ', $fields));
    foreach ($words as $word) {
        if (strpos($haystack, $word) === false) return false;
    }
    return true;
}

function icon(string $name, string $class = ''): string
{
    $paths = [
        'search' => '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.3 4.3"/>',
        'close' => '<path d="m6 6 12 12M6 18 18 6"/>',
        'arrow' => '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        'left' => '<path d="m14.5 5-7 7 7 7"/>',
        'right' => '<path d="m9.5 5 7 7-7 7"/>',
        'copy' => '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
        'external' => '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
        'film' => '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4m-4 8h4M17 8h4m-4 8h4M7 12h10"/>',
        'tv' => '<rect x="3" y="6" width="18" height="14" rx="3"/><path d="m8 2 4 4 4-4"/>',
        'check' => '<path d="m5 12 4 4L19 6"/>',
        'link' => '<path d="m10 13 4-4m-5 6-2 2a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m2 1 2-2a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0"/>',
    ];
    return '<svg class="icon ' . esc($class) . '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . ($paths[$name] ?? $paths['film']) . '</svg>';
}

function poster(array $record, bool $detail = false): void
{
    $url = coverUrl($record);
    ?>
    <div class="poster<?= $detail ? ' detail-poster' : '' ?><?= $url === '' ? ' is-missing' : '' ?>">
        <div class="poster-placeholder" aria-hidden="true">
            <?= icon('film') ?><span>等待这一帧</span><small>NO POSTER</small>
        </div>
        <?php if ($url !== ''): ?>
            <img referrerpolicy="no-referrer" src="<?= esc($url) ?>" alt="<?= esc(entryName($record)) ?>海报"
                 loading="<?= $detail ? 'eager' : 'lazy' ?>" decoding="async" width="400" height="600" data-poster>
        <?php endif; ?>
    </div>
    <?php
}

function validMagnet(array $resource): bool
{
    if (($resource['url_valid'] ?? true) === false || !is_string($resource['url'] ?? null)) return false;
    $url = $resource['url'];
    return (bool) preg_match('/^magnet:\?/i', $url)
        && !preg_match('/[\x00-\x20]/', $url)
        && (bool) preg_match('/(?:\?|&)xt=urn:(?:btih:(?:[a-f0-9]{40}|[a-z2-7]{32})|btmh:1220[a-f0-9]{64})(?:&|$)/i', rawurldecode($url));
}

function resourceBadges(array $resource): array
{
    $video = $resource['video'] ?? [];
    $labels = [];
    foreach (['resolution', 'dynamic_range_label', 'source', 'codec'] as $key) {
        if (!empty($video[$key])) $labels[] = $video[$key];
    }
    foreach (($resource['audio'] ?? []) as $audio) {
        $description = trim(implode(' ', array_filter([$audio['codec'] ?? '', $audio['channels'] ?? '', !empty($audio['atmos']) ? 'Atmos' : ''])));
        if ($description !== '') $labels[] = $description;
    }
    array_push($labels, ...strings($resource['subtitle_labels'] ?? []));
    return array_values(array_unique($labels));
}

function detailPanel(array $record, string $type, string $backUrl): void
{
    $resources = is_array($record['magnet_links'] ?? null) ? $record['magnet_links'] : [];
    $name = entryName($record);
    $facts = [
        '导演' => implode(' / ', strings($record['directors'] ?? [])),
        '主演' => implode(' / ', array_slice(strings($record['cast'] ?? []), 0, 8)),
        '类型' => implode(' / ', strings($record['genres'] ?? [])),
        '地区' => implode(' / ', strings($record['countries'] ?? [])),
        '语言' => implode(' / ', strings($record['languages'] ?? [])),
    ];
    if (!empty($record['episode_count'])) $facts['集数'] = $record['episode_count'] . ' 集';
    if (!empty($record['duration_minutes'])) $facts['片长'] = $record['duration_minutes'] . ' 分钟' . (($record['duration_scope'] ?? '') === 'episode' ? ' / 集' : '');
    ?>
    <div class="detail-bar"><span><?= $type === 'movie' ? '电影详情' : '剧集详情' ?></span>
        <a class="icon-button close-detail" href="<?= esc($backUrl) ?>" aria-label="关闭详情"><?= icon('close') ?></a>
    </div>
    <div class="detail-body">
        <div class="detail-heading">
            <?php poster($record, true); ?>
            <div class="detail-intro">
                <div class="eyebrow"><?= $type === 'movie' ? 'CINEMA' : 'SERIES' ?> <span>/</span> <?= esc($record['year'] ?? '年份未收录') ?></div>
                <h2 id="detail-title"><?= esc($name) ?></h2>
                <?php if (!empty($record['original_name']) && $record['original_name'] !== $name): ?>
                    <p class="original-name"><?= esc($record['original_name']) ?></p>
                <?php endif; ?>
                <div class="ratings">
                    <?php foreach (['douban' => '豆瓣', 'imdb' => 'IMDb'] as $key => $label):
                        $source = $record['external_sources'][$key] ?? [];
                        if (!is_numeric($source['rating'] ?? null)) continue;
                        $url = webUrl($source['url'] ?? ''); ?>
                        <a class="rating" <?= $url !== '' ? 'href="' . esc($url) . '" target="_blank" rel="noopener noreferrer"' : '' ?>>
                            <span><?= $label ?></span><strong><?= number_format((float) $source['rating'], 1) ?></strong><small>/ 10</small>
                        </a>
                    <?php endforeach; ?>
                </div>
                <dl class="facts">
                    <?php foreach ($facts as $label => $value): if ($value === '') continue; ?>
                        <div><dt><?= $label ?></dt><dd><?= esc($value) ?></dd></div>
                    <?php endforeach; ?>
                </dl>
            </div>
        </div>
        <?php if (!empty($record['synopsis'])): ?>
            <section class="synopsis-section"><h3>故事简介</h3><p class="synopsis"><?= esc($record['synopsis']) ?></p></section>
        <?php endif; ?>
        <section class="resource-section" aria-labelledby="resources-title">
            <div class="section-heading"><h3 id="resources-title">资源版本 <span><?= count($resources) ?></span></h3><small>选择适合你的画质与大小</small></div>
            <?php if (!$resources): ?>
                <div class="resource-empty"><?= icon('film') ?><p>暂未收录资源链接</p></div>
            <?php else: ?>
                <div class="resource-list">
                <?php foreach ($resources as $index => $resource):
                    $valid = validMagnet($resource);
                    $url = $resource['url'] ?? '';
                    ?>
                    <article class="resource<?= !$valid ? ' resource-invalid' : '' ?>">
                        <div class="resource-topline"><span class="resource-index">VERSION <?= str_pad((string) ($index + 1), 2, '0', STR_PAD_LEFT) ?></span>
                            <?php if (!empty($resource['size_text'])): ?><strong class="resource-size"><?= esc($resource['size_text']) ?></strong><?php endif; ?>
                        </div>
                        <h4><?= esc($resource['resource_name'] ?? '未命名版本') ?></h4>
                        <div class="resource-bottom"><div class="badges">
                            <?php foreach (resourceBadges($resource) as $badge): ?><span><?= esc($badge) ?></span><?php endforeach; ?>
                        </div><div class="resource-actions">
                            <?php if ($valid): ?>
                                <button type="button" class="button button-copy" data-copy="<?= esc($url) ?>" aria-label="复制第 <?= $index + 1 ?> 个版本的磁力链接"><?= icon('copy') ?><span>复制磁力</span></button>
                                <a class="button button-gold" href="<?= esc($url) ?>" aria-label="打开第 <?= $index + 1 ?> 个版本的下载">打开下载 <?= icon('external') ?></a>
                            <?php else: ?><span class="invalid-label">来源链接格式有误</span><?php endif; ?>
                        </div></div>
                    </article>
                <?php endforeach; ?>
                </div>
            <?php endif; ?>
        </section>
        <div class="detail-footer"><span>找到喜欢的故事，享受接下来的时光。</span>
            <?php if ($url = webUrl($record['original_url'] ?? '')): ?><a href="<?= esc($url) ?>" target="_blank" rel="noopener noreferrer">来源页面 <?= icon('external') ?></a><?php endif; ?>
        </div>
    </div>
    <?php
}

$type = array_key_exists(param('type'), CATALOGS) ? param('type') : 'movie';
$label = $type === 'movie' ? '电影' : '剧集';
$query = param('q');
$query = function_exists('mb_substr') ? mb_substr($query, 0, 100, 'UTF-8') : substr($query, 0, 300);
$itemId = filter_var(param('item'), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]) ?: null;
$isFragment = param('view') === 'detail';
$error = null;
$records = [];
try { $records = readCatalog($type); } catch (RuntimeException $e) { $error = $e->getMessage(); http_response_code(503); }

$selected = null;
if ($itemId !== null && $error === null) {
    foreach ($records as $record) {
        if ((int) $record['id'] === $itemId) { $selected = $record; break; }
    }
}
if ($isFragment) {
    if ($error !== null || $selected === null) {
        if ($error === null) http_response_code(404);
        echo '<div class="detail-bar"><span>暂时无法打开</span><a class="icon-button close-detail" href="' . esc(catalogUrl($type, $query)) . '" aria-label="关闭详情">' . icon('close') . '</a></div><div class="detail-error"><h2 id="detail-title">' . ($error !== null ? '目录暂不可用' : '未找到这个条目') . '</h2><p>' . esc($error ?? '它可能已从本地目录移除，请刷新目录再试。') . '</p></div>';
    } else {
        detailPanel($selected, $type, catalogUrl($type, $query));
    }
    exit;
}

$catalogCount = count($records);
$words = preg_split('/\s+/u', lower($query), -1, PREG_SPLIT_NO_EMPTY) ?: [];
$filtered = $words ? array_values(array_filter($records, static fn(array $r) => matches($r, $words))) : $records;
$count = count($filtered);
$pages = max(1, (int) ceil($count / PAGE_SIZE));
$requestedPage = filter_var(param('page', '1'), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]) ?: 1;
$page = min($requestedPage, $pages);
$pageItems = array_slice($filtered, ($page - 1) * PAGE_SIZE, PAGE_SIZE);
$baseUrl = catalogUrl($type, $query, $page);
if ($itemId !== null && $selected === null && $error === null) http_response_code(404);
?>
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="dark">
    <meta name="theme-color" content="#111212">
    <meta name="description" content="帧藏 4K 影库，发现电影与剧集，轻松查找资源版本。">
    <title><?= esc($selected ? entryName($selected) : ($query !== '' ? $query . ' · 搜索' : $label)) ?> · 帧藏 4K</title>
    <link rel="icon" href="data:image/svg+xml,<?= rawurlencode('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#d8ba7d"/><text x="32" y="42" text-anchor="middle" font-family="Arial" font-weight="bold" font-size="30" fill="#171714">4K</text></svg>') ?>">
    <style>
        :root{--bg:#111212;--surface:#1a1b1b;--raised:#212222;--line:#2b2c2b;--text:#eeeee9;--muted:#9a9c97;--gold:#d8ba7d;--soft-gold:#25241e;--radius:10px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--text);background:var(--bg);font-synthesis:none;color-scheme:dark}
        *{box-sizing:border-box}body{margin:0}a{color:inherit;text-decoration:none}button,input{font:inherit}button,a,input{-webkit-tap-highlight-color:transparent}button{cursor:pointer}button:disabled{cursor:default}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--gold);outline-offset:5px}button{color:inherit}::selection{background:#d8ba7d44;color:#fff}svg{flex:none}.icon{display:inline-block;width:20px;height:20px;vertical-align:middle}.container{width:min(1400px,calc(100% - 112px));margin:auto}.skip-link{position:fixed;left:20px;top:-60px;z-index:100;background:var(--gold);color:#171714;padding:12px 20px}.skip-link:focus{top:12px}
        .site-header{border-bottom:1px solid var(--line);background:#121313}.header-inner{height:96px;display:flex;align-items:center;justify-content:space-between;gap:30px}.brand{display:flex;align-items:center;gap:14px;flex:none}.brand-mark{background:var(--gold);color:#151612;border-radius:8px;width:45px;height:45px;display:grid;place-items:center;font-weight:800;font-size:22px;letter-spacing:-1.5px}.brand-name{font-size:21px;letter-spacing:4px;font-weight:600}.brand-caption{display:block;font-size:9px;letter-spacing:2.1px;color:var(--muted);margin-top:5px}.category-nav{display:flex;gap:6px;background:#1b1c1b;border:1px solid var(--line);border-radius:50px;padding:5px}.category-nav a{display:flex;align-items:center;justify-content:center;gap:9px;padding:10px 25px;border-radius:40px;font-size:14px;color:#a8aaa5;transition:background .2s,color .2s}.category-nav a:hover{color:var(--text);background:#252623}.category-nav a.active{background:var(--gold);color:#202018;font-weight:650}.category-nav .icon{width:17px;height:17px}.header-note{font-size:12px;letter-spacing:1px;color:var(--muted);display:flex;align-items:center;gap:9px}.header-note:before{content:"";width:5px;height:5px;border-radius:50%;background:var(--gold)}
        .hero{padding:57px 0 42px;display:flex;align-items:flex-end;justify-content:space-between;gap:48px}.eyebrow{font-size:10px;letter-spacing:2.6px;font-weight:550;color:var(--gold)}.eyebrow span{padding:0 10px;color:#5e605b}.hero h1{font-weight:500;font-size:clamp(29px,3.1vw,43px);letter-spacing:1px;margin:17px 0 12px;line-height:1.35}.hero h1 em{font-style:normal;color:var(--gold)}.hero p{color:var(--muted);font-size:13px;margin:0;letter-spacing:.5px;line-height:1.8}.search-form{width:420px;max-width:45%;padding-bottom:3px;flex:none}.search-box{display:flex;align-items:center;gap:12px;background:#1c1d1c;border:1px solid #353630;border-radius:10px;padding:6px 6px 6px 16px;transition:border-color .2s,box-shadow .2s}.search-box:focus-within{border-color:var(--gold);box-shadow:0 0 0 3px #d8ba7d0d}.search-box>.icon{color:#848781;width:19px}.search-box input{background:transparent;border:0;outline:none!important;color:var(--text);font-size:13px;min-width:0;flex:1;height:39px;width:100%;padding:0}.search-box input::-webkit-search-cancel-button{display:none}.search-box input::placeholder{color:#858781}.search-submit{border:0;border-radius:6px;background:var(--gold);color:#232117;font-size:13px;font-weight:650;padding:12px 17px;flex:none}.search-submit:hover{background:#ebce95}.search-clear{border:0;padding:5px;background:transparent;color:var(--muted);display:grid;place-items:center}.search-clear .icon{width:16px;height:16px}.search-hint{font-size:11px;color:#7e817a;margin:10px 0 0 2px;letter-spacing:.4px}
        .collection-header{display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid var(--line);padding:26px 0 24px}.collection-title{display:flex;align-items:center;gap:12px;min-width:0}.collection-title h2{font-size:17px;font-weight:550;margin:0;overflow-wrap:anywhere}.count{font-size:12px;color:var(--muted);border-left:1px solid #3c3e37;padding-left:12px;white-space:nowrap}.page-indicator{font-size:12px;color:#8c8f87;white-space:nowrap;font-variant-numeric:tabular-nums}.page-indicator strong{color:#d9dcd3;font-weight:500}.query-description{margin:-5px 0 24px;font-size:13px;color:var(--muted);overflow-wrap:anywhere}.query-description strong{color:var(--gold);font-weight:500}.query-description a{margin-left:14px;text-decoration:underline;text-underline-offset:4px;color:var(--text)}
        .poster-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:31px 23px}.movie-card{min-width:0;position:relative}.card-link{display:block;border-radius:var(--radius);outline-offset:7px!important}.poster{position:relative;aspect-ratio:2/3;overflow:hidden;background:#20221e;border-radius:var(--radius);isolation:isolate}.poster img{display:block;width:100%;height:100%;object-fit:cover;position:relative;z-index:1;transition:transform .4s,opacity .2s;background:#20221e}.poster-placeholder{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:11px;background:radial-gradient(ellipse at 30% 10%,#36372b,transparent 70%),linear-gradient(145deg,#252722,#181a18);color:#a7aa99}.poster-placeholder:before{content:"";position:absolute;inset:16px;border:1px solid #d8ba7d1a;border-radius:5px}.poster-placeholder .icon{width:33px;height:33px;color:#aaa587;opacity:.7;margin-bottom:6px}.poster-placeholder span{font-size:12px;letter-spacing:2px}.poster-placeholder small{font-size:8px;letter-spacing:3px;color:#72766c}.poster.is-missing img{display:none}.poster.is-loading img{opacity:0}.poster-overlay{position:absolute;inset:0;z-index:2;background:linear-gradient(180deg,#0002,transparent 20%,transparent 65%,#0009);border:1px solid #ffffff0a;border-radius:var(--radius);pointer-events:none}.card-badges{position:absolute;inset:12px 11px auto;display:flex;justify-content:space-between;align-items:flex-start;z-index:3;gap:8px;pointer-events:none}.quality-badge{font-size:10px;letter-spacing:.3px;font-weight:750;line-height:1;background:#141713dc;backdrop-filter:blur(8px);padding:6px 7px;border-radius:4px;border:1px solid #ffffff21;color:#f0eee4}.quality-badge.gold{background:var(--gold);border-color:transparent;color:#252117}.score-badge{display:flex;align-items:center;gap:4px;font-size:11px;color:#ecd199;background:#171911db;backdrop-filter:blur(8px);padding:5px 7px;border-radius:4px;font-variant-numeric:tabular-nums}.score-badge span{font-size:9px}.card-reveal{position:absolute;bottom:14px;left:0;right:0;text-align:center;font-size:11px;letter-spacing:1px;color:white;z-index:3;opacity:0;transform:translateY(6px);transition:opacity .25s,transform .25s}.card-reveal .icon{width:15px;height:15px;margin-left:5px}.card-link:hover .poster img,.card-link:focus-visible .poster img{transform:scale(1.045)}.card-link:hover .card-reveal,.card-link:focus-visible .card-reveal{opacity:1;transform:translateY(0)}.card-title{font-size:14px;font-weight:550;line-height:1.5;margin:13px 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .2s}.card-link:hover .card-title{color:var(--gold)}.card-meta{display:flex;justify-content:space-between;gap:6px;color:#92958c;font-size:11px;line-height:1.5}.card-meta>span:first-child{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.card-meta .versions{white-space:nowrap;flex:none;color:#757a6d}.card-meta i{font-style:normal;padding:0 5px;color:#5a5e53}
        .pagination-wrap{display:flex;align-items:center;justify-content:space-between;gap:25px;border-top:1px solid var(--line);margin-top:45px;padding:29px 0 42px}.range-label{font-size:12px;color:#898d82;white-space:nowrap}.pagination{display:flex;gap:7px;align-items:center}.page-link,.page-gap{width:36px;height:36px;display:grid;place-items:center;border:1px solid transparent;border-radius:7px;font-size:12px;font-variant-numeric:tabular-nums}.page-link{background:#1d1f1b;color:#b3b6ac}.page-link:hover{border-color:#676750;color:var(--text)}.page-link.current{background:var(--gold);color:#252317;font-weight:700}.page-link.disabled{opacity:.3;pointer-events:none}.page-link .icon{width:16px;height:16px}.page-gap{width:22px;color:#686e60}.page-jump{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px}.page-jump input{border:1px solid #393e30;background:#1a1e17;border-radius:5px;width:47px;height:31px;color:var(--text);text-align:center;appearance:textfield}.page-jump input::-webkit-inner-spin-button{appearance:none}.page-jump button{background:none;border:0;color:var(--gold);padding:6px 0}.empty-state{text-align:center;padding:75px 20px 95px;border:1px dashed #34382f;border-radius:12px;min-height:300px}.empty-state>.icon{width:42px;height:42px;color:#9a9f8c}.empty-state h2{font-size:21px;font-weight:500;margin:23px 0 12px}.empty-state p{font-size:14px;color:var(--muted);line-height:1.8}.empty-state .button{margin-top:15px}.site-footer{border-top:1px solid var(--line);padding:27px 0 33px}.footer-inner{display:flex;align-items:center;justify-content:space-between;gap:20px;font-size:11px;color:#74796b;letter-spacing:.5px}.footer-brand{color:#a5aa9a;letter-spacing:2px}.footer-brand span{color:var(--gold);font-size:12px;font-weight:650;letter-spacing:0;margin-right:9px}
        .detail-dialog{padding:0;border:1px solid #3d4037;border-radius:16px;width:min(940px,calc(100vw - 56px));max-width:none;max-height:90dvh;margin:auto;color:var(--text);background:#171917;box-shadow:0 35px 100px #0008;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#41463b transparent}.detail-dialog::backdrop{background:#080a08c9;backdrop-filter:blur(8px)}.detail-bar{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid var(--line);background:#191b18;position:sticky;top:0;z-index:4;font-size:12px;color:var(--muted);letter-spacing:1px}.icon-button{border:1px solid #383d31;background:#252a20;border-radius:50%;width:33px;height:33px;display:grid;place-items:center;color:#d3d8c8}.icon-button .icon{width:17px;height:17px}.icon-button:hover{background:#3a4030;color:#fff}.detail-body{padding:30px}.detail-heading{display:grid;grid-template-columns:185px 1fr;gap:30px}.detail-poster{align-self:start;box-shadow:0 8px 35px #0003}.detail-intro{padding-top:8px;min-width:0}.detail-intro h2{font-size:29px;font-weight:550;line-height:1.4;letter-spacing:.2px;margin:12px 0 5px;overflow-wrap:anywhere}.original-name{color:var(--muted);font-size:13px;margin:4px 0 14px;line-height:1.6;overflow-wrap:anywhere}.ratings{display:flex;flex-wrap:wrap;gap:20px;margin:14px 0 18px}.rating{display:flex;align-items:baseline;gap:8px}.rating span{font-size:11px;color:#bec3b4}.rating strong{font-size:25px;font-weight:550;color:var(--gold);font-variant-numeric:tabular-nums}.rating small{font-size:10px;color:#707a63}.rating[href]:hover strong{color:#f8d994}.facts{margin:15px 0 0}.facts>div{display:flex;gap:16px;font-size:12px;line-height:1.9;margin:5px 0}.facts dt{color:#828b77;flex:none;width:26px}.facts dd{margin:0;color:#c2c8b8;overflow-wrap:anywhere}.synopsis-section{border-top:1px solid var(--line);margin-top:28px;padding-top:25px}.detail-body h3{font-size:15px;font-weight:550;margin:0 0 14px}.synopsis{font-size:13px;line-height:1.95;letter-spacing:.2px;color:#a6b09a;margin:0;white-space:pre-line}.resource-section{margin-top:30px}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:16px}.section-heading h3{margin:0}.section-heading h3 span{font-size:11px;color:var(--gold);background:#d8ba7d15;border-radius:4px;padding:3px 7px;margin-left:7px}.section-heading>small{font-size:11px;color:#828b75}.resource-list{display:flex;flex-direction:column;gap:12px}.resource{padding:19px 20px 18px;background:#1e221b;border:1px solid #333a2c;border-radius:9px}.resource-topline{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:9px}.resource-index{font-size:9px;letter-spacing:1.5px;color:#88967a}.resource-size{font-size:12px;font-weight:550;color:var(--gold);font-variant-numeric:tabular-nums}.resource h4{font-size:12px;font-weight:450;line-height:1.75;color:#d3dacb;overflow-wrap:anywhere;margin:0 0 15px}.resource-bottom{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}.badges{display:flex;gap:5px;flex-wrap:wrap;align-items:center}.badges span{font-size:9px;line-height:1.4;padding:4px 6px;background:#292f24;border:1px solid #3c4533;border-radius:4px;color:#aabb99}.resource-actions{display:flex;gap:8px;flex:none}.button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:35px;padding:8px 12px;border-radius:6px;font-size:11px;font-weight:550;line-height:1.4;border:1px solid #47523b;white-space:nowrap;background:#272f20;color:#c8d7b8;transition:background .2s}.button .icon{width:14px;height:14px}.button:hover{background:#34412a}.button-gold{background:var(--gold);border-color:var(--gold);color:#29291a}.button-gold:hover{background:#efd29b}.button-copy.is-copied{color:#abd796;border-color:#71915f}.invalid-label{font-size:11px;color:#cda899}.resource-invalid{opacity:.7}.resource-empty{text-align:center;border:1px dashed #394331;border-radius:9px;padding:30px;color:#8e9e7e;font-size:13px}.resource-empty .icon{width:30px;height:30px}.detail-footer{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-top:27px;font-size:10px;color:#7f8a72;line-height:1.8}.detail-footer a{color:#adbb9c;white-space:nowrap}.detail-footer .icon{width:12px;height:12px;margin-left:5px}.detail-loading,.detail-error{text-align:center;padding:80px 30px;color:var(--muted);font-size:14px;line-height:1.8}.detail-error h2{color:var(--text);font-size:22px;font-weight:500}.spinner{display:block;width:30px;height:30px;border:2px solid #414b37;border-top-color:var(--gold);border-radius:50%;margin:0 auto 18px;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.toast{position:fixed;bottom:30px;left:50%;transform:translate(-50%,15px);z-index:20;padding:13px 22px;border:1px solid #576348;background:#252e1e;color:#e0e8d7;border-radius:9px;box-shadow:0 10px 35px #0005;font-size:13px;opacity:0;pointer-events:none;transition:opacity .2s,transform .2s;max-width:calc(100% - 30px);text-align:center}.toast.visible{opacity:1;transform:translate(-50%,0)}.manual-copy{margin-top:12px;width:100%;padding:10px;border:1px solid #657355;background:#11180d;color:var(--text);border-radius:5px;font:11px/1.7 monospace;resize:vertical;min-height:75px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}[hidden]{display:none!important}
        @media(min-width:1600px){.container{width:min(1450px,calc(100% - 140px))}.poster-grid{gap:34px 27px}.hero{padding-top:65px;padding-bottom:48px}}
        @media(max-width:1250px){.container{width:calc(100% - 72px)}.poster-grid{grid-template-columns:repeat(5,minmax(0,1fr));gap:28px 20px}.search-form{width:365px}.hero{gap:28px}.header-note{font-size:10px}.page-jump{display:none}}
        @media(max-width:1000px){.poster-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.header-note{display:none}.hero{align-items:flex-start;flex-direction:column;gap:26px;padding-top:36px;padding-bottom:28px}.search-form{width:100%;max-width:100%}.search-hint{display:none}.hero h1{font-size:36px}.header-inner{height:83px}.detail-heading{grid-template-columns:160px 1fr;gap:24px}.detail-intro h2{font-size:25px}.resource-bottom{flex-direction:column;align-items:flex-start;gap:15px}.resource-actions{align-self:flex-end}}
        @media(max-width:700px){.container{width:calc(100% - 40px)}.poster-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:26px 16px}.brand-caption{font-size:8px;letter-spacing:1px}.brand-name{font-size:18px;letter-spacing:3px}.brand-mark{width:38px;height:38px;font-size:20px;border-radius:6px}.brand{gap:10px}.category-nav a{padding:8px 17px;gap:6px;font-size:12px}.category-nav .icon{width:15px;height:15px}.category-nav{gap:2px;padding:4px}.hero h1{font-size:31px}.hero{padding-top:31px}.eyebrow{font-size:9px;letter-spacing:2px}.collection-header{padding:23px 0 20px}.collection-title h2{font-size:16px}.card-badges{inset:9px 8px auto;gap:4px}.card-title{font-size:13px}.card-meta{font-size:10px}.card-meta .versions{display:none}.card-reveal{display:none}.pagination-wrap{flex-direction:column;gap:18px;padding-top:22px;margin-top:31px}.pagination{order:-1}.footer-inner{font-size:10px}.footer-inner>span:last-child{max-width:50%;text-align:right;line-height:1.8}.detail-dialog{width:calc(100vw - 24px);max-height:94dvh;border-radius:12px}.detail-bar{padding:0 20px;height:57px}.detail-body{padding:23px 20px}.detail-heading{grid-template-columns:120px 1fr;gap:20px}.detail-intro{padding-top:4px}.detail-intro h2{font-size:21px;margin-top:9px}.original-name{font-size:11px}.facts>div{font-size:11px;gap:10px}.ratings{gap:15px;margin:10px 0}.rating{gap:5px}.rating strong{font-size:22px}.synopsis{font-size:12px}.resource{padding:16px}.section-heading>small{font-size:10px}.detail-footer>span{display:none}.detail-footer{justify-content:flex-end}.score-badge{font-size:10px;padding:4px 5px}.quality-badge{font-size:9px;padding:5px 6px}}
        @media(max-width:480px){.container{width:calc(100% - 36px)}.header-inner{height:79px;gap:12px}.brand-caption{font-size:7px;letter-spacing:1.1px}.brand-name{font-size:17px}.brand-mark{width:35px;height:35px;font-size:18px}.category-nav a{padding:8px 12px}.category-nav .icon{display:none}.poster-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:25px 16px}.hero{gap:22px}.hero h1{font-size:29px;letter-spacing:0;margin:13px 0 9px}.hero p{font-size:12px}.search-box{padding-left:12px;gap:9px}.search-box input{font-size:12px}.search-submit{padding:11px 14px}.count{font-size:11px}.page-indicator{font-size:11px}.card-title{font-size:14px;margin-top:11px}.card-meta{font-size:11px}.card-meta .versions{display:inline}.card-badges{inset:10px 9px auto}.quality-badge{font-size:10px}.score-badge{font-size:11px}.page-link{width:32px;height:34px}.pagination{gap:5px}.page-gap{width:16px}.detail-dialog{width:100vw;height:100dvh;max-height:100dvh;border:0;border-radius:0}.detail-body{padding:22px 18px}.detail-heading{grid-template-columns:94px 1fr;gap:16px}.detail-intro h2{font-size:20px}.detail-heading .facts{grid-column:1/-1}.facts>div{line-height:1.75}.ratings{gap:12px}.rating strong{font-size:20px}.rating small{display:none}.synopsis-section{margin-top:23px;padding-top:22px}.resource-section{margin-top:26px}.section-heading{align-items:center;gap:10px}.section-heading>small{max-width:130px;text-align:right;line-height:1.6}.resource{padding:16px 14px}.resource-actions{width:100%}.resource-actions .button{flex:1;min-height:38px}.resource h4{font-size:11px}.footer-inner{align-items:flex-start}.toast{bottom:18px;font-size:12px}.empty-state{padding:55px 18px 65px}.query-description{font-size:12px}}
        @media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
    </style>
</head>
<body>
<a class="skip-link" href="#collection">跳至影片目录</a>
<header class="site-header">
    <div class="container header-inner">
        <a class="brand" href="?type=movie" aria-label="帧藏 4K 首页"><span class="brand-mark">4K</span><span><span class="brand-name">帧藏</span><span class="brand-caption">THE FRAME ARCHIVE</span></span></a>
        <nav class="category-nav" aria-label="影视分类">
            <?php foreach (['movie' => '电影', 'series' => '剧集'] as $key => $text): ?>
                <a href="<?= esc(catalogUrl($key, $query)) ?>" <?= $key === $type ? 'class="active" aria-current="page"' : '' ?>><?= icon($key === 'movie' ? 'film' : 'tv') ?><?= $text ?></a>
            <?php endforeach; ?>
        </nav>
        <span class="header-note">好故事，值得被收藏</span>
    </div>
</header>
<main class="container">
    <section class="hero" aria-labelledby="hero-title">
        <div><div class="eyebrow">A LITTLE ESCAPE. A BIGGER WORLD.</div><h1 id="hero-title">把今晚，交给<em>好故事。</em></h1><p>从一帧画面开始，发现下一部心之所向。</p></div>
        <form class="search-form" method="get" role="search">
            <input type="hidden" name="type" value="<?= $type ?>">
            <label class="sr-only" for="search">搜索<?= $label ?>：片名、导演、演员或标签</label>
            <div class="search-box"><?= icon('search') ?><input id="search" type="search" name="q" value="<?= esc($query) ?>" placeholder="搜索<?= $label ?>、导演、演员…" maxlength="100" enterkeyhint="search" autocomplete="off">
                <button class="search-clear" type="button" aria-label="清空搜索" <?= $query === '' ? 'hidden' : '' ?>><?= icon('close') ?></button>
                <button class="search-submit" type="submit">搜索</button>
            </div>
            <div class="search-hint">也可以试试原名、别名或喜欢的类型</div>
        </form>
    </section>
    <section id="collection" aria-labelledby="collection-title">
        <div class="collection-header"><div class="collection-title"><h2 id="collection-title"><?= $query !== '' ? '搜索结果' : '全部' . $label ?></h2><span class="count"><?= number_format($count) ?> 个条目</span></div><div class="page-indicator">第 <strong><?= $page ?></strong> / <?= $pages ?> 页</div></div>
        <?php if ($query !== ''): ?><p class="query-description">在<?= $label ?>中查找 <strong>“<?= esc($query) ?>”</strong><a href="<?= esc(catalogUrl($type)) ?>">清除搜索</a></p><?php endif; ?>
        <?php if ($error !== null): ?>
            <div class="empty-state"><?= icon('film') ?><h2>目录暂时无法读取</h2><p><?= esc($error) ?></p><a href="<?= esc($baseUrl) ?>" class="button button-gold">重新加载</a></div>
        <?php elseif ($count === 0): ?>
            <div class="empty-state"><?= icon($query !== '' ? 'search' : 'film') ?><h2><?= $query !== '' ? '还没找到这个故事' : '好故事，即将入场' ?></h2><p><?= $query !== '' ? '试试更短的片名、原名，或切换到另一分类。' : '当前分类暂未收录内容。' ?></p><?php if ($query !== ''): ?><a class="button button-gold" href="<?= esc(catalogUrl($type)) ?>">浏览全部<?= $label ?> <?= icon('arrow') ?></a><?php endif; ?></div>
        <?php else: ?>
            <div class="poster-grid">
                <?php foreach ($pageItems as $record):
                    $resources = $record['magnet_links'] ?? [];
                    $resolutions = array_filter(array_map(static fn($r) => $r['video']['resolution'] ?? '', $resources));
                    $has4k = (bool) array_filter($resolutions, static fn($v) => strtolower($v) === '2160p');
                    $quality = $has4k ? '4K' : (in_array('1080p', array_map('strtolower', $resolutions), true) ? '1080P' : '');
                    $score = $record['external_sources']['douban']['rating'] ?? null;
                    $genres = strings($record['genres'] ?? []);
                    ?>
                    <article class="movie-card"><a class="card-link" href="<?= esc(catalogUrl($type, $query, $page, (int) $record['id'])) ?>" data-detail="<?= (int) $record['id'] ?>" aria-label="查看<?= esc(entryName($record)) ?>的详情">
                        <div style="position:relative">
                            <?php poster($record); ?><div class="poster-overlay"></div>
                            <div class="card-badges"><span><?php if ($quality !== ''): ?><span class="quality-badge<?= $has4k ? ' gold' : '' ?>"><?= $quality ?></span><?php endif; ?></span>
                                <?php if (is_numeric($score)): ?><span class="score-badge" aria-label="豆瓣 <?= esc($score) ?> 分"><span>★</span> <?= number_format((float) $score, 1) ?></span><?php endif; ?>
                            </div><span class="card-reveal">查看资源 <?= icon('arrow') ?></span>
                        </div>
                        <h3 class="card-title" title="<?= esc(entryName($record)) ?>"><?= esc(entryName($record)) ?></h3>
                        <div class="card-meta"><span><?= esc($record['year'] ?? '年份待补') ?><?php if ($genres): ?><i>·</i><?= esc($genres[0]) ?><?php endif; ?></span><span class="versions"><?= count($resources) ?> 个版本</span></div>
                    </a></article>
                <?php endforeach; ?>
            </div>
            <div class="pagination-wrap"><span class="range-label">正在浏览 <?= number_format(($page - 1) * PAGE_SIZE + 1) ?>–<?= number_format(min($page * PAGE_SIZE, $count)) ?> / <?= number_format($count) ?> 个条目</span>
                <nav class="pagination" aria-label="目录分页">
                    <?php if ($page > 1): ?><a class="page-link" href="<?= esc(catalogUrl($type, $query, $page - 1)) ?>" aria-label="上一页"><?= icon('left') ?></a><?php else: ?><span class="page-link disabled" aria-disabled="true"><?= icon('left') ?></span><?php endif; ?>
                    <?php
                    $visiblePages = array_unique(array_merge([1, $pages], range(max(1, $page - 1), min($pages, $page + 1))));
                    sort($visiblePages);
                    $previous = 0;
                    foreach ($visiblePages as $number):
                        if ($previous && $number > $previous + 1): ?><span class="page-gap" aria-hidden="true">…</span><?php endif;
                        if ($number === $page): ?><span class="page-link current" aria-current="page" aria-label="第 <?= $number ?> 页"><?= $number ?></span>
                        <?php else: ?><a class="page-link" href="<?= esc(catalogUrl($type, $query, $number)) ?>" aria-label="第 <?= $number ?> 页"><?= $number ?></a><?php endif;
                        $previous = $number;
                    endforeach; ?>
                    <?php if ($page < $pages): ?><a class="page-link" href="<?= esc(catalogUrl($type, $query, $page + 1)) ?>" aria-label="下一页"><?= icon('right') ?></a><?php else: ?><span class="page-link disabled" aria-disabled="true"><?= icon('right') ?></span><?php endif; ?>
                </nav>
                <form class="page-jump" method="get"><input type="hidden" name="type" value="<?= $type ?>"><?php if ($query !== ''): ?><input type="hidden" name="q" value="<?= esc($query) ?>"><?php endif; ?><label for="jump-page">前往</label><input id="jump-page" type="number" name="page" min="1" max="<?= $pages ?>" value="<?= $page ?>" aria-label="跳转页码"><button type="submit" aria-label="跳转到指定页"><?= icon('arrow') ?></button></form>
            </div>
        <?php endif; ?>
    </section>
</main>
<footer class="site-footer"><div class="container footer-inner"><span class="footer-brand"><span>4K</span> 帧藏 · THE FRAME ARCHIVE</span><span>让每一场观看，都值得期待。</span></div></footer>
<dialog class="detail-dialog" id="detail-dialog" aria-labelledby="detail-title" data-base-url="<?= esc($baseUrl) ?>" <?= $itemId !== null ? 'open' : '' ?>>
    <div id="detail-content"><?php if ($selected !== null): detailPanel($selected, $type, $baseUrl); elseif ($itemId !== null): ?><div class="detail-bar"><span>未找到条目</span><a class="icon-button close-detail" href="<?= esc($baseUrl) ?>" aria-label="关闭详情"><?= icon('close') ?></a></div><div class="detail-error"><h2 id="detail-title">未找到这个条目</h2><p>请返回目录重新选择。</p></div><?php endif; ?></div>
</dialog>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
<noscript><style>.search-clear,.button-copy{display:none}.detail-dialog[open]{position:fixed;inset:20px;z-index:10;box-shadow:0 0 0 100vmax #080a08d9}.card-reveal{display:none}</style></noscript>
<script>
(() => {
    'use strict';
    const dialog = document.querySelector('#detail-dialog');
    const content = document.querySelector('#detail-content');
    const search = document.querySelector('#search');
    const clearSearch = document.querySelector('.search-clear');
    const toast = document.querySelector('#toast');
    let toastTimer, lastFocus, controller, activeItem;
    let detailWasPushed = false;
    const detailCache = new Map();

    function prepareImages(root = document) {
        root.querySelectorAll('img[data-poster]').forEach(img => {
            if (img.dataset.prepared) return;
            img.dataset.prepared = '1';
            const failed = () => {
                img.closest('.poster').classList.add('is-missing');
            };
            img.addEventListener('error', failed);
            if (img.complete && img.naturalWidth === 0) failed();
        });
    }
    prepareImages();

    clearSearch.addEventListener('click', () => {
        search.value = '';
        search.form.requestSubmit();
    });
    search.addEventListener('input', () => clearSearch.hidden = !search.value);

    function notify(message) {
        clearTimeout(toastTimer);
        (dialog.open ? dialog : document.body).append(toast);
        toast.textContent = message;
        toast.classList.add('visible');
        toastTimer = setTimeout(() => toast.classList.remove('visible'), 2800);
    }
    function lockPage() { document.documentElement.style.overflow = 'hidden'; }
    function unlockPage() { document.documentElement.style.overflow = ''; }
    function showDialog() {
        if (!dialog.open) dialog.showModal();
        lockPage();
    }
    function focusClose() { content.querySelector('.close-detail')?.focus({preventScroll: true}); }
    function closeDialog(updateHistory = true) {
        controller?.abort();
        activeItem = null;
        if (dialog.open) dialog.close();
        unlockPage();
        if (updateHistory && new URL(location.href).searchParams.has('item')) {
            if (detailWasPushed || history.state?.detail) history.back();
            else history.replaceState(null, '', dialog.dataset.baseUrl);
        }
        detailWasPushed = false;
        lastFocus?.focus({preventScroll: true});
    }

    async function openDetail(url, push = true) {
        if (!('showModal' in dialog)) { location.href = url; return; }
        controller?.abort();
        const target = new URL(url, location.href);
        const item = target.searchParams.get('item');
        const key = `${target.searchParams.get('type')}:${item}`;
        activeItem = key;
        if (!dialog.open) lastFocus = document.activeElement;
        if (push) {
            history.pushState({detail: true}, '', target);
            detailWasPushed = true;
        }
        content.innerHTML = '<div class="detail-bar"><span>正在打开</span><button type="button" class="icon-button close-detail" aria-label="关闭详情">×</button></div><div class="detail-loading"><span class="spinner" aria-hidden="true"></span><h2 id="detail-title" class="sr-only">正在加载详情</h2>正在展开这个故事…</div>';
        showDialog();
        dialog.scrollTop = 0;
        focusClose();
        if (detailCache.has(key)) {
            content.innerHTML = detailCache.get(key);
            prepareImages(content);
            focusClose();
            return;
        }
        controller = new AbortController();
        const signal = controller.signal;
        target.searchParams.set('view', 'detail');
        try {
            const response = await fetch(target, {signal, headers: {'Accept': 'text/html'}});
            const html = await response.text();
            if (signal.aborted || activeItem !== key) return;
            if (!response.headers.get('content-type')?.includes('text/html') || !html.includes('id="detail-title"')) throw new Error('invalid response');
            if (response.ok) {
                if (detailCache.size >= 12) detailCache.delete(detailCache.keys().next().value);
                detailCache.set(key, html);
            }
            content.innerHTML = html;
            prepareImages(content);
            focusClose();
        } catch (error) {
            if (error.name === 'AbortError') return;
            if (activeItem !== key) return;
            content.innerHTML = '<div class="detail-bar"><span>加载失败</span><button type="button" class="icon-button close-detail" aria-label="关闭详情">×</button></div><div class="detail-error"><h2 id="detail-title">这次没能打开</h2><p>请检查网络后重试。</p><button type="button" class="button button-gold" data-retry>重新加载</button></div>';
            focusClose();
        }
    }

    document.addEventListener('click', async event => {
        const card = event.target.closest('a[data-detail]');
        if (card && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
            event.preventDefault();
            openDetail(card.href);
            return;
        }
        if (event.target.closest('.close-detail')) {
            event.preventDefault();
            closeDialog();
            return;
        }
        if (event.target.closest('[data-retry]')) { openDetail(location.href, false); return; }
        const button = event.target.closest('[data-copy]');
        if (!button) return;
        const magnet = button.dataset.copy;
        let copied = false;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(magnet);
                copied = true;
            }
        } catch (_) { /* Fall through for browsers that deny clipboard access. */ }
        if (!copied) {
            const field = document.createElement('textarea');
            field.value = magnet;
            field.setAttribute('readonly', '');
            field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;width:1px;height:1px';
            content.append(field);
            field.select();
            try { copied = document.execCommand('copy'); } catch (_) {}
            field.remove();
            button.focus({preventScroll: true});
        }
        if (copied) {
            button.classList.add('is-copied');
            button.querySelector('span').textContent = '已复制';
            notify('磁力链接已复制');
            setTimeout(() => { button.classList.remove('is-copied'); button.querySelector('span').textContent = '复制磁力'; }, 1800);
        } else {
            const resource = button.closest('.resource');
            let field = resource.querySelector('.manual-copy');
            if (!field) {
                field = document.createElement('textarea');
                field.className = 'manual-copy';
                field.readOnly = true;
                field.setAttribute('aria-label', '磁力链接，请手动复制');
                field.value = magnet;
                resource.append(field);
            }
            field.focus(); field.select();
            notify('浏览器未允许复制，请长按或按 ⌘/Ctrl+C 复制');
        }
    });

    dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
    let backdropDown = false;
    dialog.addEventListener('pointerdown', event => { backdropDown = event.target === dialog; });
    dialog.addEventListener('click', event => {
        if (event.target !== dialog || !backdropDown) return;
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog();
    });
    window.addEventListener('popstate', () => {
        const item = new URL(location.href).searchParams.get('item');
        if (item) openDetail(location.href, false);
        else closeDialog(false);
    });
    if (dialog.hasAttribute('open') && 'showModal' in dialog) {
        dialog.removeAttribute('open');
        showDialog();
        focusClose();
    }
})();
</script>
</body>
</html>
