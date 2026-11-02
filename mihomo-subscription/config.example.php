<?php
declare(strict_types=1);

// Copy to config.php. The real configuration stays outside the public web root.
return [
    'access_password' => 'CHANGE_ME',
    'rule_update_interval' => 86400,
    // Personal exceptions take precedence over community rules.
    'direct_domains' => [],
    'proxy_domains' => [],
    'reject_domains' => [],
    // Paste node exports here. VLESS authentication uses password, not uuid.
    'nodes' => [
        [
            'title' => 'Example-Hysteria2',
            'type' => 'Hysteria2',
            'host' => 'hy2.example.test',
            'port' => '443',
            'peer' => 'hy2.example.test',
            'password' => 'EXAMPLE_NODE_PASSWORD',
            'obfs' => 'none',
        ],
        [
            'title' => 'Example-Reality',
            'type' => 'VLESS',
            'host' => 'reality.example.test',
            'port' => '443',
            'peer' => 'www.example.com',
            'password' => '11111111-1111-4111-8111-111111111111',
            'tls' => true,
            'tlsProfile' => 'chrome',
            'xtls' => 2,
            'publicKey' => 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
            'shortId' => '0123456789abcdef',
        ],
    ],
];
