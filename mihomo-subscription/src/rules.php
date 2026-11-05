<?php
declare(strict_types=1);

final class RuleSourceUnavailable extends RuntimeException {}

/** URLs are fixed here, never taken from request parameters. */
function communityRuleSources(): array
{
    $base = 'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/';
    return [
        'private-domain' => ['behavior' => 'domain', 'url' => $base . 'geosite/private.list', 'encoding' => 'text'],
        'private-ip' => ['behavior' => 'ipcidr', 'url' => $base . 'geoip/private.list', 'encoding' => 'text'],
        'cn-domain' => ['behavior' => 'domain', 'url' => $base . 'geosite/cn.list', 'encoding' => 'text'],
        'cn-ip' => ['behavior' => 'ipcidr', 'url' => $base . 'geoip/cn.list', 'encoding' => 'text'],
        'google' => ['behavior' => 'domain', 'url' => $base . 'geosite/google.list', 'encoding' => 'text'],
        'youtube' => ['behavior' => 'domain', 'url' => $base . 'geosite/youtube.list', 'encoding' => 'text'],
        'overseas' => ['behavior' => 'domain', 'url' => $base . 'geosite/geolocation-!cn.list', 'encoding' => 'text'],
        'ads' => ['behavior' => 'domain', 'url' => 'https://raw.githubusercontent.com/privacy-protection-tools/anti-AD/master/anti-ad-clash.yaml', 'encoding' => 'domain-yaml'],
    ];
}

function validCommunityRule(string $rule, string $behavior): bool
{
    if ($behavior === 'domain') {
        return strlen($rule) <= 255
            && preg_match('/^(?:\+\.|\.)?[a-z0-9_*?-]+(?:\.[a-z0-9_*?-]+)*\.?$/iD', $rule) === 1;
    }
    if (!preg_match('/^([^\/]+)\/(\d{1,3})$/D', $rule, $match)) {
        return false;
    }
    $address = @inet_pton($match[1]);
    return $address !== false && (int) $match[2] <= strlen($address) * 8;
}

/** Parse only the upstreams' flat lists, not arbitrary YAML. Reject any invalid line. */
function parseCommunityRules(string $body, array $source): array
{
    if ($body === '' || strlen($body) > 16 * 1024 * 1024) {
        throw new RuleSourceUnavailable('Rule response is empty or too large.');
    }
    $body = preg_replace('/^\xEF\xBB\xBF/', '', $body);
    $yaml = $source['encoding'] === 'domain-yaml';
    $hasPayload = false;
    $rules = [];
    foreach (preg_split('/\r\n|\n|\r/', $body) as $line) {
        $line = trim($line);
        if ($line === '' || str_starts_with($line, '#')) {
            continue;
        }
        if ($yaml) {
            if (!$hasPayload && $line === 'payload:') {
                $hasPayload = true;
                continue;
            }
            if (!$hasPayload || !preg_match('/^-\s+(.+)$/D', $line, $match)) {
                throw new RuleSourceUnavailable('Unexpected rule list format.');
            }
            $line = trim($match[1]);
            if (str_starts_with($line, "'")) {
                if (!str_ends_with($line, "'")) {
                    throw new RuleSourceUnavailable('Invalid quoted rule.');
                }
                $line = substr($line, 1, -1);
            } elseif (str_starts_with($line, '"')) {
                try {
                    $line = json_decode($line, true, 8, JSON_THROW_ON_ERROR);
                } catch (JsonException $error) {
                    throw new RuleSourceUnavailable('Invalid quoted rule.');
                }
            }
        }
        if (!is_string($line) || !validCommunityRule($line, $source['behavior'])) {
            throw new RuleSourceUnavailable('Invalid rule entry.');
        }
        $rules[$line] = true;
    }
    if ($rules === []) {
        throw new RuleSourceUnavailable('Rule list contains no entries.');
    }
    // Preserve exact-domain and +.suffix semantics; never flatten them into suffixes.
    return array_map('strval', array_keys($rules));
}

function validateCommunityPayloads(array $payloads): void
{
    $sources = communityRuleSources();
    if (array_diff_key($payloads, $sources) || array_diff_key($sources, $payloads)) {
        throw new RuleSourceUnavailable('Incomplete community rule snapshot.');
    }
    foreach ($sources as $name => $source) {
        $rules = $payloads[$name];
        if (!is_array($rules) || !array_is_list($rules) || $rules === [] || count($rules) > 500000) {
            throw new RuleSourceUnavailable('Invalid community rule snapshot.');
        }
        foreach ($rules as $rule) {
            if (!is_string($rule) || !validCommunityRule($rule, $source['behavior'])) {
                throw new RuleSourceUnavailable('Invalid cached rule entry.');
            }
        }
    }
}

/** Bounded, verified HTTPS download; cURL is optional. */
function fetchCommunityRule(string $url, float $timeout): string
{
    $limit = 16 * 1024 * 1024;
    if (function_exists('curl_init')) {
        $body = '';
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT_MS => (int) (min(5, $timeout) * 1000),
            CURLOPT_TIMEOUT_MS => max(1, (int) ($timeout * 1000)),
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_USERAGENT => 'mihomo-subscription/2',
            CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$body, $limit): int {
                if (strlen($body) + strlen($chunk) > $limit) {
                    return 0;
                }
                $body .= $chunk;
                return strlen($chunk);
            },
        ]);
        try {
            $ok = curl_exec($curl);
            if ($ok === false || curl_getinfo($curl, CURLINFO_HTTP_CODE) !== 200) {
                throw new RuleSourceUnavailable('Upstream rule request failed.');
            }
        } finally {
            curl_close($curl);
        }
        return $body;
    }

    $deadline = microtime(true) + $timeout;
    $context = stream_context_create([
        'http' => ['timeout' => $timeout, 'follow_location' => 0, 'ignore_errors' => true,
            'header' => "User-Agent: mihomo-subscription/2\r\nConnection: close\r\n"],
        'ssl' => ['verify_peer' => true, 'verify_peer_name' => true],
    ]);
    $stream = @fopen($url, 'rb', false, $context);
    if ($stream === false) {
        throw new RuleSourceUnavailable('Upstream rule request failed.');
    }
    try {
        $metadata = stream_get_meta_data($stream);
        $headers = $metadata['wrapper_data'] ?? [];
        if (!preg_match('/^HTTP\/\S+ 200(?:\s|$)/', $headers[0] ?? '')) {
            throw new RuleSourceUnavailable('Upstream did not return HTTP 200.');
        }
        $body = '';
        while (!feof($stream)) {
            $remaining = $deadline - microtime(true);
            if ($remaining <= 0) {
                throw new RuleSourceUnavailable('Upstream rule request timed out.');
            }
            stream_set_timeout($stream, (int) $remaining, (int) (($remaining - (int) $remaining) * 1000000));
            $chunk = fread($stream, 65536);
            if ($chunk === false || stream_get_meta_data($stream)['timed_out']) {
                throw new RuleSourceUnavailable('Upstream rule response was interrupted.');
            }
            $body .= $chunk;
            if (strlen($body) > $limit) {
                throw new RuleSourceUnavailable('Upstream rule response is too large.');
            }
        }
        foreach ($headers as $header) {
            if (preg_match('/^Content-Length:\s*(\d+)\s*$/i', $header, $match) && (int) $match[1] !== strlen($body)) {
                throw new RuleSourceUnavailable('Incomplete upstream response.');
            }
        }
        return $body;
    } finally {
        fclose($stream);
    }
}

function communitySourceHash(): string
{
    return hash('sha256', json_encode(communityRuleSources(), JSON_THROW_ON_ERROR));
}

function readCommunityCache(string $path): ?array
{
    if (!is_file($path)) {
        return null;
    }
    $raw = @file_get_contents($path, false, null, 0, 32 * 1024 * 1024 + 1);
    if ($raw === false || strlen($raw) > 32 * 1024 * 1024) {
        return null;
    }
    try {
        $cache = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        if (!is_array($cache) || ($cache['version'] ?? null) !== 1
            || ($cache['sources_hash'] ?? '') !== communitySourceHash()
            || !is_int($cache['updated_at'] ?? null) || $cache['updated_at'] <= 0
            || $cache['updated_at'] > time() + 300 || !is_array($cache['payloads'] ?? null)) {
            return null;
        }
        validateCommunityPayloads($cache['payloads']);
        return $cache;
    } catch (Throwable $error) {
        return null;
    }
}

function writeCommunityCache(string $path, array $cache): void
{
    $temp = @tempnam(dirname($path), '.rules-');
    if ($temp === false) {
        throw new RuleSourceUnavailable('Cannot create rule cache file.');
    }
    try {
        if (realpath(dirname($temp)) !== realpath(dirname($path))) {
            throw new RuleSourceUnavailable('Rule cache temporary file is not on the same filesystem.');
        }
        $json = json_encode($cache, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        if (@file_put_contents($temp, $json) !== strlen($json) || !@rename($temp, $path)) {
            throw new RuleSourceUnavailable('Cannot save rule cache.');
        }
    } finally {
        if (is_file($temp)) {
            @unlink($temp);
        }
    }
}

/** Refresh all eight lists as a unit. Never publish a partial snapshot. */
function loadCommunityRules(array $settings, ?callable $fetch = null, bool $force = false): array
{
    $ttl = $settings['rule_update_interval'] ?? 86400;
    $timeout = $settings['rule_fetch_timeout'] ?? 15;
    $budget = $settings['rule_refresh_budget'] ?? 25;
    $dir = $settings['rule_cache_dir'] ?? dirname(__DIR__) . '/.cache';
    if (!is_int($ttl) || $ttl < 60 || !is_int($timeout) || $timeout < 1 || $timeout > 60
        || !is_int($budget) || $budget < 1 || $budget > 300 || !is_string($dir) || $dir === '') {
        throw new InvalidArgumentException('Invalid rule cache settings.');
    }
    $dir = rtrim($dir, '/');
    $path = $dir . '/rules-v1.json';
    $cached = readCommunityCache($path);
    if (!$force && $cached !== null && time() - $cached['updated_at'] < $ttl) {
        return $cached + ['stale' => false];
    }
    $fallback = static function () use ($cached): array {
        if ($cached !== null) {
            return $cached + ['stale' => true];
        }
        throw new RuleSourceUnavailable('No complete community rule cache is available.');
    };
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        return $fallback();
    }
    $lock = @fopen($dir . '/refresh.lock', 'c');
    if ($lock === false) {
        return $fallback();
    }
    try {
        if (!flock($lock, LOCK_EX | LOCK_NB)) {
            return $fallback();
        }
        // Recheck after taking the lock; another request may have just refreshed it.
        $latest = readCommunityCache($path);
        if (!$force && $latest !== null && time() - $latest['updated_at'] < $ttl) {
            return $latest + ['stale' => false];
        }
        $lastAttempt = @filemtime($dir . '/last-attempt');
        if (!$force && $lastAttempt !== false && time() - $lastAttempt < 300) {
            return $fallback();
        }
        if (!@touch($dir . '/last-attempt')) {
            return $fallback();
        }
        $fetch ??= 'fetchCommunityRule';
        $deadline = microtime(true) + $budget;
        $payloads = [];
        try {
            foreach (communityRuleSources() as $name => $source) {
                $remaining = $deadline - microtime(true);
                if ($remaining <= 0) {
                    throw new RuleSourceUnavailable('Rule refresh exceeded its time budget.');
                }
                $payloads[$name] = parseCommunityRules($fetch($source['url'], min($timeout, $remaining)), $source);
            }
            validateCommunityPayloads($payloads);
            $snapshot = ['version' => 1, 'sources_hash' => communitySourceHash(), 'updated_at' => time(), 'payloads' => $payloads];
            writeCommunityCache($path, $snapshot);
            return $snapshot + ['stale' => false];
        } catch (Throwable $error) {
            error_log('mihomo-subscription: rule refresh failed; retaining the last complete snapshot if available');
            return $fallback();
        }
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}
