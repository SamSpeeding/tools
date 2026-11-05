<?php
declare(strict_types=1);

require_once __DIR__ . '/rules.php';

/** HTTP handling is independent of config loading, so tests never need real secrets. */
function subscriptionResponse(array $settings, array $server, array $query, ?callable $ruleLoader = null): array
{
    $method = $server['REQUEST_METHOD'] ?? 'GET';
    if (!in_array($method, ['GET', 'HEAD'], true)) {
        $response = subscriptionError(405, 'Use GET or HEAD.');
        $response['headers']['Allow'] = 'GET, HEAD';
        return $response;
    }

    $expected = $settings['access_password'] ?? '';
    if (!is_string($expected) || $expected === '' || $expected === 'CHANGE_ME') {
        return subscriptionError(500, 'Set access_password in config.php first.');
    }
    $authorization = $server['HTTP_AUTHORIZATION'] ?? $server['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
    $provided = $query['password'] ?? null;
    if ($authorization !== null) {
        $provided = is_string($authorization) && preg_match('/^Bearer (\S+)$/iD', $authorization, $match)
            ? $match[1] : null;
    }
    if (!is_string($provided) || !hash_equals($expected, $provided)) {
        return subscriptionError(401, 'Missing or incorrect subscription password.');
    }

    $format = $query['format'] ?? 'yaml';
    if (!in_array($format, ['yaml', 'json'], true)) {
        return subscriptionError(400, 'format must be yaml or json.');
    }

    try {
        $snapshot = ($ruleLoader ?? 'loadCommunityRules')($settings);
        $config = buildMihomoConfig($settings, $snapshot['payloads']);
        $body = $format === 'json'
            ? json_encode($config, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR) . "\n"
            : "# Generated mihomo subscription. All community rules are embedded.\n" . encodeYaml($config);
    } catch (RuleSourceUnavailable $error) {
        $response = subscriptionError(503, 'Community rules unavailable. Warm the server cache and retry.');
        $response['headers']['Retry-After'] = '300';
        return $response;
    } catch (Throwable $error) {
        // Do not echo node values, exception messages or the request URL into logs.
        error_log('mihomo-subscription: invalid subscription settings');
        return subscriptionError(500, 'Invalid subscription configuration.');
    }

    return [
        'status' => 200,
        'headers' => subscriptionHeaders() + [
            'Content-Type' => $format === 'json' ? 'application/json; charset=utf-8' : 'application/yaml; charset=utf-8',
            'Content-Disposition' => 'inline; filename="mihomo.' . $format . '"',
            // Client hint in hours; inline rules update when the whole config is reloaded.
            'profile-update-interval' => '24',
            'X-Rules-Updated-At' => gmdate('Y-m-d\TH:i:s\Z', $snapshot['updated_at']),
            'X-Rules-Cache' => $snapshot['stale'] ? 'stale' : 'fresh',
        ],
        'body' => $body,
    ];
}

function subscriptionHeaders(): array
{
    return [
        'Cache-Control' => 'private, no-store',
        'X-Content-Type-Options' => 'nosniff',
        'Referrer-Policy' => 'no-referrer',
    ];
}

function subscriptionError(int $status, string $message): array
{
    return [
        'status' => $status,
        'headers' => subscriptionHeaders() + ['Content-Type' => 'application/json; charset=utf-8'],
        'body' => json_encode(['error' => $message], JSON_THROW_ON_ERROR) . "\n",
    ];
}

function requiredString(array $node, string $field): string
{
    $value = $node[$field] ?? null;
    if (!is_string($value) || trim($value) === '') {
        throw new InvalidArgumentException('Missing node field: ' . $field);
    }
    return $value;
}

/** Convert the supported Shadowrocket-style exports to mihomo node entries. */
function convertNode(array $node): array
{
    $port = filter_var($node['port'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 65535]]);
    if ($port === false) {
        throw new InvalidArgumentException('Invalid node port.');
    }
    $type = strtolower(requiredString($node, 'type'));
    $base = [
        'name' => requiredString($node, 'title'),
        'type' => $type,
        'server' => requiredString($node, 'host'),
        'port' => $port,
    ];
    $password = requiredString($node, 'password');
    $peer = requiredString($node, 'peer');

    if ($type === 'hysteria2') {
        if (!in_array($node['obfs'] ?? 'none', ['', 'none'], true)) {
            throw new InvalidArgumentException('Only un-obfuscated Hysteria2 is configured by this converter.');
        }
        return $base + ['password' => $password, 'sni' => $peer, 'skip-cert-verify' => false];
    }
    if ($type !== 'vless') {
        throw new InvalidArgumentException('Unsupported node type.');
    }
    if (!preg_match('/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/iD', $password)) {
        throw new InvalidArgumentException('VLESS password must contain the authentication UUID.');
    }
    if (($node['tls'] ?? false) !== true || !in_array($node['xtls'] ?? null, [0, 2], true)) {
        throw new InvalidArgumentException('Expected VLESS TLS with xtls 0 or 2.');
    }
    $publicKey = requiredString($node, 'publicKey');
    $decodedKey = base64_decode(strtr($publicKey, '-_', '+/'), true);
    $shortId = requiredString($node, 'shortId');
    if ($decodedKey === false || strlen($decodedKey) !== 32 || !preg_match('/^(?:[0-9a-f]{2}){1,8}$/iD', $shortId)) {
        throw new InvalidArgumentException('Invalid Reality public key or short ID.');
    }
    $result = $base + [
        'uuid' => $password,
        'network' => 'tcp',
        'udp' => true,
        'tls' => true,
        'servername' => $peer,
        'client-fingerprint' => ($node['tlsProfile'] ?? '') ?: 'chrome',
        'skip-cert-verify' => false,
        'reality-opts' => ['public-key' => $publicKey, 'short-id' => $shortId],
    ];
    if ($node['xtls'] === 2) {
        $result['flow'] = 'xtls-rprx-vision';
    }
    return $result;
}

function buildMihomoConfig(array $settings, ?array $payloads = null): array
{
    $settings = applyCustomSettings($settings);
    $nodes = $settings['nodes'] ?? [];
    if (!is_array($nodes) || $nodes === []) {
        throw new InvalidArgumentException('At least one node is required.');
    }
    $proxies = array_map('convertNode', array_values($nodes));
    $names = array_column($proxies, 'name');
    $reserved = ['PROXY', 'AUTO', 'GOOGLE', 'YOUTUBE', 'ADS', 'FINAL', 'DIRECT', 'REJECT', 'GLOBAL'];
    if (count(array_unique($names)) !== count($names) || array_intersect($names, $reserved)) {
        throw new InvalidArgumentException('Duplicate or reserved node names.');
    }
    $interval = $settings['rule_update_interval'] ?? 86400;
    if (!is_int($interval) || $interval < 60) {
        throw new InvalidArgumentException('Rule interval must be at least 60 seconds.');
    }
    $payloads ??= loadCommunityRules($settings)['payloads'];
    validateCommunityPayloads($payloads);
    $providers = [];
    foreach (communityRuleSources() as $name => $source) {
        $providers[$name] = [
            'type' => 'inline', 'behavior' => $source['behavior'],
            'payload' => $payloads[$name],
        ];
    }

    $rules = ['RULE-SET,private-domain,DIRECT', 'RULE-SET,private-ip,DIRECT,no-resolve'];
    foreach (['direct_domains' => 'DIRECT', 'proxy_domains' => 'PROXY', 'reject_domains' => 'REJECT'] as $key => $target) {
        $domains = $settings[$key] ?? [];
        if (!is_array($domains)) {
            throw new InvalidArgumentException('Personal domain exceptions must be arrays.');
        }
        foreach ($domains as $domain) {
            if (!is_string($domain) || !preg_match('/^(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/iD', $domain)) {
                throw new InvalidArgumentException('Use a domain name without a scheme or port.');
            }
            $rules[] = 'DOMAIN-SUFFIX,' . strtolower($domain) . ',' . $target;
        }
    }
    foreach ($settings['custom']['rules'] ?? [] as $rule) {
        $rules[] = $rule;
    }
    array_push($rules,
        'RULE-SET,ads,ADS',
        'RULE-SET,youtube,YOUTUBE',
        'RULE-SET,google,GOOGLE',
        'RULE-SET,overseas,PROXY',
        'RULE-SET,cn-domain,DIRECT',
        'RULE-SET,cn-ip,DIRECT',
        'MATCH,FINAL'
    );

    $domesticDns = ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query'];
    $dnsPolicy = ['rule-set:cn-domain,private-domain' => $domesticDns];
    foreach ($settings['direct_domains'] ?? [] as $domain) {
        $dnsPolicy['+.' . strtolower($domain)] = $domesticDns;
    }
    foreach ($settings['proxy_domains'] ?? [] as $domain) {
        $dnsPolicy['+.' . strtolower($domain)] = ['https://1.1.1.1/dns-query#PROXY'];
    }
    // Do not require the proxy to resolve its own server names during bootstrap.
    foreach ($proxies as $node) {
        $dnsPolicy[$node['server']] = $domesticDns;
    }

    $config = [
        'mixed-port' => 7890,
        'allow-lan' => false,
        'bind-address' => '127.0.0.1',
        'mode' => 'rule',
        'log-level' => 'info',
        'ipv6' => false,
        'profile' => ['store-selected' => true],
        // ShellCrash/client integration owns TUN, firewall and LAN DNS interception.
        'dns' => [
            'enable' => true,
            'listen' => '127.0.0.1:1053',
            'ipv6' => false,
            'enhanced-mode' => 'fake-ip',
            'fake-ip-range' => '198.18.0.1/16',
            'fake-ip-filter' => ['*.lan', '*.local', '+.localhost'],
            'default-nameserver' => ['223.5.5.5', '119.29.29.29'],
            'proxy-server-nameserver' => $domesticDns,
            'direct-nameserver' => $domesticDns,
            'nameserver' => ['https://1.1.1.1/dns-query#PROXY', 'https://8.8.8.8/dns-query#PROXY'],
            'nameserver-policy' => $dnsPolicy,
        ],
        'proxies' => $proxies,
        'proxy-groups' => [
            ['name' => 'PROXY', 'type' => 'select', 'proxies' => array_merge(['AUTO'], $names)],
            ['name' => 'AUTO', 'type' => 'url-test', 'proxies' => $names,
                'url' => 'https://www.gstatic.com/generate_204', 'interval' => 300, 'tolerance' => 80],
            ['name' => 'GOOGLE', 'type' => 'select', 'proxies' => array_merge(['PROXY'], $names)],
            ['name' => 'YOUTUBE', 'type' => 'select', 'proxies' => array_merge(['PROXY'], $names)],
            ['name' => 'ADS', 'type' => 'select', 'proxies' => ['REJECT', 'DIRECT']],
            ['name' => 'FINAL', 'type' => 'select', 'proxies' => ['PROXY', 'DIRECT']],
        ],
        'rule-providers' => $providers,
        'rules' => $rules,
    ];
    if (($settings['custom']['hosts'] ?? []) !== []) {
        $config['hosts'] = $settings['custom']['hosts'];
    }
    return mergeMihomoOverrides($config, $settings['custom']['overrides'] ?? []);
}

/** Personal edits live separately from credentials and generated community data. */
function applyCustomSettings(array $settings): array
{
    $custom = $settings['custom'] ?? [];
    $allowed = ['direct_domains', 'proxy_domains', 'reject_domains', 'rules', 'hosts', 'overrides'];
    if (!is_array($custom) || array_diff(array_keys($custom), $allowed)) {
        throw new InvalidArgumentException('Unknown custom configuration field.');
    }
    foreach ($custom as $value) {
        if (!is_array($value)) {
            throw new InvalidArgumentException('Custom configuration fields must be arrays.');
        }
    }
    foreach (['direct_domains', 'proxy_domains', 'reject_domains'] as $key) {
        $base = $settings[$key] ?? [];
        $extra = $custom[$key] ?? [];
        if (!is_array($base) || !array_is_list($base) || !array_is_list($extra)) {
            throw new InvalidArgumentException('Custom domains must be lists.');
        }
        $settings[$key] = array_merge($base, $extra);
    }
    if (!array_is_list($custom['rules'] ?? [])) {
        throw new InvalidArgumentException('Custom rules must be a list.');
    }
    foreach ($custom['rules'] ?? [] as $rule) {
        if (!is_string($rule) || $rule === '' || preg_match('/[\x00-\x1f]/', $rule) || !str_contains($rule, ',')) {
            throw new InvalidArgumentException('Custom rules must use single-line mihomo rule syntax.');
        }
    }
    foreach ($custom['hosts'] ?? [] as $host => $value) {
        if (!is_string($host) || $host === '' || (!is_string($value) && !is_array($value))) {
            throw new InvalidArgumentException('Invalid custom host mapping.');
        }
        if (is_array($value) && (!array_is_list($value) || $value === [] || count(array_filter($value, 'is_string')) !== count($value))) {
            throw new InvalidArgumentException('Host address lists must contain strings.');
        }
    }
    $overrides = $custom['overrides'] ?? [];
    if (($overrides !== [] && array_is_list($overrides))
        || array_intersect(array_keys($overrides), ['proxies', 'proxy-groups', 'rule-providers', 'rules', 'hosts'])) {
        throw new InvalidArgumentException('Use the dedicated fields for nodes, rules and hosts.');
    }
    return $settings;
}

/** Maps merge recursively; lists and scalar values replace the existing value. */
function mergeMihomoOverrides(array $base, array $overrides): array
{
    foreach ($overrides as $key => $value) {
        if (!is_string($key) || $key === '') {
            throw new InvalidArgumentException('Override map keys must be nonempty strings.');
        }
        if (is_array($value) && $value !== [] && !array_is_list($value)
            && isset($base[$key]) && is_array($base[$key]) && !array_is_list($base[$key])) {
            $base[$key] = mergeMihomoOverrides($base[$key], $value);
        } else {
            $base[$key] = $value;
        }
    }
    return $base;
}

/** Serialize only the scalar/list/map subset used by this service; quote every string. */
function encodeYaml(array $value, int $indent = 0): string
{
    $output = '';
    $list = array_is_list($value);
    foreach ($value as $key => $item) {
        $prefix = str_repeat(' ', $indent) . ($list ? '-' : yamlScalar((string) $key) . ':');
        if (is_array($item) && $item !== []) {
            $output .= $prefix . "\n" . encodeYaml($item, $indent + 2);
        } else {
            $output .= $prefix . ' ' . (is_array($item) ? '[]' : yamlScalar($item)) . "\n";
        }
    }
    return $output;
}

function yamlScalar(mixed $value): string
{
    if (!is_scalar($value) && $value !== null) {
        throw new InvalidArgumentException('Unsupported YAML value.');
    }
    return json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
}
