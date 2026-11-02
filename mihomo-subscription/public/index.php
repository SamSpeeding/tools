<?php
declare(strict_types=1);

ini_set('display_errors', '0');
require dirname(__DIR__) . '/src/subscription.php';

try {
    if (!is_file(dirname(__DIR__) . '/config.php')) {
        throw new RuntimeException('Missing private settings.');
    }
    $settings = require dirname(__DIR__) . '/config.php';
    $response = subscriptionResponse($settings, $_SERVER, $_GET);
} catch (Throwable $error) {
    error_log('mihomo-subscription: unable to load configuration');
    $response = subscriptionError(500, 'Subscription configuration is unavailable.');
}

http_response_code($response['status']);
foreach ($response['headers'] as $name => $value) {
    header($name . ': ' . $value);
}
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'HEAD') {
    echo $response['body'];
}
