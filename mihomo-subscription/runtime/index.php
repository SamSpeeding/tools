<?php
// Standalone deployment entry: no source tree, cache, network downloads or YAML extension.
declare(strict_types=1);
ini_set('display_errors', '0');

function bundleError(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'HEAD') {
        echo json_encode(['error' => $message]) . "\n";
    }
    exit;
}

header('Cache-Control: private, no-store');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if (!in_array($method, ['GET', 'HEAD'], true)) {
    header('Allow: GET, HEAD');
    bundleError(405, 'Use GET or HEAD.');
}

// Read metadata and data through the same handle. An FTP rename cannot mix versions,
// and PHP OPcache never caches the changing configuration or embedded rule contents.
$file = @fopen(__DIR__ . '/config.php', 'rb');
if ($file === false) {
    bundleError(503, 'Publish a complete configuration bundle first.');
}
try {
    $guard = fgets($file, 256);
    if ($guard !== "<?php http_response_code(404); exit; __halt_compiler();\n") {
        throw new RuntimeException('Invalid bundle guard.');
    }
    $line = fgets($file, 16384);
    $meta = json_decode($line === false ? '' : $line, true, 16, JSON_THROW_ON_ERROR);
    $offset = ftell($file);
    $stat = fstat($file);
    if (!is_array($meta) || ($meta['version'] ?? null) !== 1
        || !is_string($meta['auth_sha256'] ?? null)
        || !preg_match('/^[a-f0-9]{64}$/D', $meta['auth_sha256'])
        || !is_int($meta['rules_updated_at'] ?? null) || $meta['rules_updated_at'] <= 0
        || !is_string($meta['revision'] ?? null) || !preg_match('/^[a-f0-9]{64}$/D', $meta['revision'])) {
        throw new RuntimeException('Invalid bundle metadata.');
    }
    $total = 0;
    foreach (['json', 'yaml'] as $kind) {
        $part = $meta['formats'][$kind] ?? [];
        if (!is_int($part['bytes'] ?? null) || $part['bytes'] < 1 || $part['bytes'] > 32 * 1024 * 1024
            || !is_string($part['sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/D', $part['sha256'])) {
            throw new RuntimeException('Invalid bundle segment.');
        }
        $total += $part['bytes'];
    }
    if ($offset === false || $stat === false || $stat['size'] !== $offset + $total) {
        throw new RuntimeException('Incomplete bundle.');
    }
} catch (Throwable $error) {
    fclose($file);
    bundleError(503, 'Invalid or incomplete configuration bundle.');
}

$authorization = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
$provided = $_GET['password'] ?? null;
if ($authorization !== null) {
    $provided = is_string($authorization) && preg_match('/^Bearer (\S+)$/iD', $authorization, $match)
        ? $match[1] : null;
}
if (!is_string($provided) || !hash_equals($meta['auth_sha256'], hash('sha256', $provided))) {
    fclose($file);
    bundleError(401, 'Missing or incorrect subscription password.');
}
$format = $_GET['format'] ?? 'yaml';
if (!in_array($format, ['json', 'yaml'], true)) {
    fclose($file);
    bundleError(400, 'format must be yaml or json.');
}

$start = $offset + ($format === 'yaml' ? $meta['formats']['json']['bytes'] : 0);
$length = $meta['formats'][$format]['bytes'];
$hash = hash_init('sha256');
if (fseek($file, $start) !== 0 || hash_update_stream($hash, $file, $length) !== $length
    || !hash_equals($meta['formats'][$format]['sha256'], hash_final($hash))
    || fseek($file, $start) !== 0) {
    fclose($file);
    bundleError(503, 'Configuration checksum mismatch.');
}

header('Content-Type: ' . ($format === 'json' ? 'application/json' : 'application/yaml') . '; charset=utf-8');
header('Content-Disposition: inline; filename="mihomo.' . $format . '"');
header('Content-Length: ' . $length);
header('profile-update-interval: 24');
header('X-Subscription-Mode: bundled');
header('X-Rules-Updated-At: ' . gmdate('Y-m-d\TH:i:s\Z', $meta['rules_updated_at']));
header('X-Bundle-Revision: ' . $meta['revision']);
if ($method !== 'HEAD') {
    $output = fopen('php://output', 'wb');
    stream_copy_to_stream($file, $output, $length);
    fclose($output);
}
fclose($file);
