<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
require dirname(__DIR__) . '/src/bundle.php';

try {
    $root = dirname(__DIR__);
    $settings = require $root . '/config.php';
    $settings['custom'] = is_file($root . '/custom.php') ? require $root . '/custom.php' : [];
    if (in_array('--cached', $argv, true)) {
        $snapshot = readCommunityCache(($settings['rule_cache_dir'] ?? $root . '/.cache') . '/rules-v1.json');
        if ($snapshot === null) {
            throw new RuntimeException('没有可用本地缓存，请先联网构建。');
        }
    } else {
        $settings['rule_refresh_budget'] ??= 180;
        $snapshot = loadCommunityRules($settings, null, true);
        if ($snapshot['stale']) {
            throw new RuntimeException('更新规则失败，已保留旧缓存；本次没有生成新包。');
        }
    }
    $manifest = writeDeploymentBundle($settings, $snapshot, $root . '/.build');
    echo json_encode($manifest, JSON_THROW_ON_ERROR) . "\n";
} catch (Throwable $error) {
    // Keep credentials, custom values and request URLs out of terminal output.
    fwrite(STDERR, "构建失败：请检查本地配置、上游连通性和缓存目录权限。\n");
    exit(1);
}
