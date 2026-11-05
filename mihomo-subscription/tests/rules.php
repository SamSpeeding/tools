<?php
declare(strict_types=1);

function expectUnavailable(callable $callback, string $message): void
{
    try {
        $callback();
    } catch (RuleSourceUnavailable $error) {
        check(true, $message);
        return;
    }
    check(false, $message);
}

$sources = communityRuleSources();
check(parseCommunityRules("\xEF\xBB\xBF# comment\r\nexact.example\r\n+.suffix.example\r\nexact.example\r\n", $sources['google']) === ['exact.example', '+.suffix.example'], 'Domain parsing preserves exact/suffix matching and deduplicates');
check(parseCommunityRules("# comment\npayload:\n  - '+.ads.example'\n  - \"exact.example\"\n", $sources['ads']) === ['+.ads.example', 'exact.example'], 'anti-AD YAML payload becomes inline domain entries');
check(parseCommunityRules("192.168.0.0/16\nfc00::/7\n", $sources['private-ip']) === ['192.168.0.0/16', 'fc00::/7'], 'IPv4 and IPv6 CIDRs are preserved');
foreach (['', '# empty', '<html>error</html>', "good.example\nDOMAIN-SUFFIX,evil.example,PROXY", 'payload: []'] as $body) {
    expectUnavailable(fn() => parseCommunityRules($body, $sources['google']), 'Empty/HTML/malformed upstream responses are rejected');
}
expectUnavailable(fn() => parseCommunityRules("payload:\n  - '+.good.example'\n  broken: value\n", $sources['ads']), 'One malformed YAML line rejects the complete refresh');
expectUnavailable(fn() => parseCommunityRules("10.0.0.0/33\n", $sources['private-ip']), 'Invalid CIDR prefixes are rejected');

$extra = $settings;
$extra['direct_domains'] = ['base.example'];
$extra['custom'] = [
    'direct_domains' => ['Custom.Example'],
    'proxy_domains' => ['proxy.example'],
    'reject_domains' => ['ads.personal.example'],
    'rules' => ['IP-CIDR,203.0.113.7/32,PROXY,no-resolve'],
    'hosts' => ['nas.home.arpa' => '192.168.31.100'],
    'overrides' => ['log-level' => 'warning', 'dns' => [
        'nameserver' => ['https://dns.example/dns-query'],
        'nameserver-policy' => ['+.internal.example' => ['192.168.31.1']],
    ]],
];
$merged = testConfig($extra);
check(in_array('DOMAIN-SUFFIX,base.example,DIRECT', $merged['rules'], true) && in_array('DOMAIN-SUFFIX,custom.example,DIRECT', $merged['rules'], true), 'Custom file domains append to existing config domains');
check(array_search('IP-CIDR,203.0.113.7/32,PROXY,no-resolve', $merged['rules'], true) < array_search('RULE-SET,ads,ADS', $merged['rules'], true), 'Custom native rules precede community rules');
check($merged['hosts']['nas.home.arpa'] === '192.168.31.100' && $merged['log-level'] === 'warning', 'Hosts and scalar overrides reach the final config');
check($merged['dns']['nameserver'] === ['https://dns.example/dns-query'] && isset($merged['dns']['nameserver-policy']['rule-set:cn-domain,private-domain'], $merged['dns']['nameserver-policy']['+.internal.example']), 'Nested maps merge while lists replace');
check(isset($merged['dns']['nameserver-policy']['+.proxy.example']) && $merged['dns']['enable'] === true, 'Custom proxy DNS and existing DNS fields survive merging');
$bad = $settings;
$bad['custom'] = ['overrides' => ['rule-providers' => ['remote' => ['url' => 'https://example.test']]]];
expectInvalid(fn() => testConfig($bad), 'Overrides cannot replace embedded providers with remote URLs');
$bad['custom'] = ['direct_domains' => ['bad.example,PROXY']];
expectInvalid(fn() => testConfig($bad), 'Custom domain entries cannot inject routing fields');
$bad['custom'] = ['typo_rules' => []];
expectInvalid(fn() => testConfig($bad), 'Unknown custom keys fail instead of silently ignoring edits');

$root = sys_get_temp_dir() . '/mihomo-subscription-tests-' . bin2hex(random_bytes(6));
mkdir($root, 0700);
$cacheSettings = $settings;
$cacheSettings['rule_cache_dir'] = $root . '/cache';
$bodies = [];
foreach ($sources as $source) {
    $bodies[$source['url']] = $source['encoding'] === 'domain-yaml' ? "payload:\n  - '+.ads.example'\n"
        : ($source['behavior'] === 'ipcidr' ? "10.0.0.0/8\nfc00::/7\n" : "exact.example\n+.suffix.example\n");
}
$calls = 0;
$fetch = static function (string $url, float $timeout) use ($bodies, &$calls): string {
    ++$calls;
    return $bodies[$url];
};
$never = static function (): string { throw new RuntimeException('Unexpected upstream request'); };
try {
    $snapshot = loadCommunityRules($cacheSettings, $fetch);
    check($calls === 8 && !$snapshot['stale'] && count($snapshot['payloads']) === 8, 'Cold refresh fetches and caches all eight lists');
    $cached = loadCommunityRules($cacheSettings, $never);
    check(!$cached['stale'] && $cached['payloads'] === $snapshot['payloads'], 'Fresh cache requires no upstream connectivity');

    $cachePath = $cacheSettings['rule_cache_dir'] . '/rules-v1.json';
    $expired = readCommunityCache($cachePath);
    $expired['updated_at'] = time() - 90000;
    writeCommunityCache($cachePath, $expired);
    touch($cacheSettings['rule_cache_dir'] . '/last-attempt', time() - 301);
    clearstatcache();
    $before = hash_file('sha256', $cachePath);
    $calls = 0;
    $partialFailure = static function (string $url) use (&$calls, $bodies): string {
        ++$calls;
        return $calls === 4 ? '<html>502 Bad Gateway</html>' : $bodies[$url];
    };
    $stale = loadCommunityRules($cacheSettings, $partialFailure);
    check($stale['stale'] && $calls === 4 && hash_file('sha256', $cachePath) === $before, 'Partial refresh failure preserves the complete previous snapshot');
    $calls = 0;
    $backoff = loadCommunityRules($cacheSettings, $fetch);
    check($backoff['stale'] && $calls === 0, 'Failed refreshes back off instead of downloading on every request');
    check(count($stale['payloads']) === 8, 'Failed refresh preserves every rule group');

    $lock = fopen($cacheSettings['rule_cache_dir'] . '/refresh.lock', 'c');
    flock($lock, LOCK_EX);
    check(loadCommunityRules($cacheSettings, $never, true)['stale'], 'Concurrent refresh uses the previous complete snapshot');
    flock($lock, LOCK_UN);
    fclose($lock);

    $calls = 0;
    $refreshed = loadCommunityRules($cacheSettings, $fetch, true);
    check(!$refreshed['stale'] && $calls === 8 && $refreshed['updated_at'] > $expired['updated_at'], 'A successful forced refresh atomically replaces the old snapshot');
    check(count(glob($cacheSettings['rule_cache_dir'] . '/.rules-*')) === 0, 'Successful refresh leaves no partial cache files');

    $cold = $cacheSettings;
    $cold['rule_cache_dir'] = $root . '/cold';
    expectUnavailable(fn() => loadCommunityRules($cold, $never), 'Cold upstream failure cannot produce an incomplete bundle');
    check(!is_file($cold['rule_cache_dir'] . '/rules-v1.json'), 'Cold failure never publishes a partial snapshot');
    file_put_contents($cachePath, '{broken-json');
    check(readCommunityCache($cachePath) === null, 'Corrupted cache is not treated as a valid snapshot');

    foreach ($config['rule-providers'] as $provider) {
        check($provider['type'] === 'inline' && !array_intersect(['url', 'path', 'interval'], array_keys($provider)), 'Router has no provider downloads or external rule paths');
    }
} finally {
    $files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($files as $file) {
        $file->isDir() ? rmdir($file->getPathname()) : unlink($file->getPathname());
    }
    rmdir($root);
}
