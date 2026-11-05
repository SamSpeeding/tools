<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
require dirname(__DIR__) . '/src/rules.php';

try {
    $settings = require dirname(__DIR__) . '/config.php';
    // CLI warming is not limited by the HTTP request budget.
    $settings['rule_refresh_budget'] = 180;
    $snapshot = loadCommunityRules($settings, null, true);
    if ($snapshot['stale']) {
        fwrite(STDERR, "Refresh failed; the previous complete cache is still available.\n");
        exit(1);
    }
    foreach ($snapshot['payloads'] as $name => $rules) {
        echo $name . ': ' . count($rules) . " rules\n";
    }
    echo 'Updated at ' . gmdate('c', $snapshot['updated_at']) . "\n";
} catch (Throwable $error) {
    fwrite(STDERR, "Rule refresh failed. Check upstream connectivity and cache directory permissions.\n");
    exit(1);
}
