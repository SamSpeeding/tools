<?php
declare(strict_types=1);
require_once __DIR__ . '/subscription.php';

/** Build exactly two deployable PHP files; credentials never become a static JSON URL. */
function writeDeploymentBundle(array $settings, array $snapshot, string $directory): array
{
    $password = $settings['access_password'] ?? '';
    if (!is_string($password) || $password === '' || $password === 'CHANGE_ME') {
        throw new InvalidArgumentException('Set the subscription password before building.');
    }
    $config = buildMihomoConfig($settings, $snapshot['payloads']);
    $json = json_encode($config, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR) . "\n";
    $yaml = "# Bundled mihomo subscription. All community rules are embedded.\n" . encodeYaml($config);
    $meta = [
        'version' => 1,
        'auth_sha256' => hash('sha256', $password),
        'rules_updated_at' => $snapshot['updated_at'],
        'revision' => hash('sha256', $json),
        'formats' => [
            'json' => ['bytes' => strlen($json), 'sha256' => hash('sha256', $json)],
            'yaml' => ['bytes' => strlen($yaml), 'sha256' => hash('sha256', $yaml)],
        ],
    ];
    foreach ($meta['formats'] as $format) {
        if ($format['bytes'] > 32 * 1024 * 1024) {
            throw new RuntimeException('Generated subscription is too large.');
        }
    }
    if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
        throw new RuntimeException('Cannot create build directory.');
    }
    // No PHP closing tag: requesting config.php runs the guard and returns 404.
    // Data after __halt_compiler() is never evaluated, even if a password contains PHP text.
    $header = "<?php http_response_code(404); exit; __halt_compiler();\n"
        . json_encode($meta, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
    $files = [
        'config.php' => $header . $json . $yaml,
        'index.php' => file_get_contents(dirname(__DIR__) . '/runtime/index.php'),
    ];
    $manifest = [
        'revision' => $meta['revision'],
        'rules_updated_at' => $snapshot['updated_at'],
        'rule_count' => array_sum(array_map('count', $snapshot['payloads'])),
        'formats' => $meta['formats'],
        'files' => [],
    ];
    foreach ($files as $name => $content) {
        $temp = tempnam($directory, '.bundle-');
        try {
            if ($temp === false || file_put_contents($temp, $content) !== strlen($content)
                || !rename($temp, $directory . '/' . $name)) {
                throw new RuntimeException('Cannot write deployment bundle.');
            }
            chmod($directory . '/' . $name, 0600);
        } finally {
            if ($temp !== false && is_file($temp)) {
                unlink($temp);
            }
        }
        $manifest['files'][$name] = ['bytes' => strlen($content), 'sha256' => hash('sha256', $content)];
    }
    file_put_contents($directory . '/build-info.json', json_encode($manifest, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n");
    chmod($directory . '/build-info.json', 0600);
    return $manifest;
}
