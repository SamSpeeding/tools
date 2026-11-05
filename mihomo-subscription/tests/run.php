<?php
declare(strict_types=1);

require dirname(__DIR__) . '/src/subscription.php';
$settings = require dirname(__DIR__) . '/config.example.php';
$settings['access_password'] = 'test-password';
// Deliberately differ from the actual authentication UUID to catch export mapping errors.
$settings['nodes'][1]['uuid'] = '99999999-9999-4999-8999-999999999999';
$payloads = [];
foreach (communityRuleSources() as $name => $source) {
    $payloads[$name] = $source['behavior'] === 'ipcidr' ? ['10.0.0.0/8', 'fc00::/7'] : ['exact.example', '+.suffix.example'];
}
function testConfig(array $settings): array
{
    return buildMihomoConfig($settings, $GLOBALS['payloads']);
}
$passed = 0;
function check(bool $condition, string $message): void
{
    global $passed;
    if (!$condition) {
        throw new RuntimeException('FAIL: ' . $message);
    }
    ++$passed;
    echo 'PASS: ' . $message . "\n";
}
function expectInvalid(callable $callback, string $message): void
{
    try {
        $callback();
    } catch (InvalidArgumentException $error) {
        check(true, $message);
        return;
    }
    check(false, $message);
}

$config = testConfig($settings);
$reality = $config['proxies'][1];
check($reality['uuid'] === $settings['nodes'][1]['password'], 'VLESS uses password as its authentication UUID');
check($reality['flow'] === 'xtls-rprx-vision' && $reality['reality-opts']['short-id'] === '0123456789abcdef', 'Vision and Reality fields are preserved');
check($config['proxies'][0]['password'] === 'EXAMPLE_NODE_PASSWORD' && $config['proxies'][0]['skip-cert-verify'] === false, 'Hysteria2 preserves password and certificate verification');
$noFlow = $settings['nodes'][1];
$noFlow['xtls'] = 0;
check(!isset(convertNode($noFlow)['flow']), 'xtls 0 does not enable Vision');
check(count($config['rule-providers']) === 8 && $config['rule-providers']['ads']['type'] === 'inline', 'All eight community lists are inline providers');
check($config['rule-providers']['ads']['payload'] === $payloads['ads'] && !isset($config['rule-providers']['ads']['url']), 'Rule contents are embedded without upstream URLs');
check(end($config['rules']) === 'MATCH,FINAL' && $config['proxy-groups'][5]['proxies'][0] === 'PROXY', 'Unmatched traffic defaults to proxy');
check(!isset($config['tun']) && $config['allow-lan'] === false, 'Base subscription leaves device traffic interception to its manager');
$custom = $settings;
$custom['direct_domains'] = ['Allowed.Example'];
$custom['proxy_domains'] = ['blocked.example'];
$custom['reject_domains'] = ['tracking.example'];
$customConfig = testConfig($custom);
check(array_search('DOMAIN-SUFFIX,allowed.example,DIRECT', $customConfig['rules'], true) < array_search('RULE-SET,ads,ADS', $customConfig['rules'], true), 'Personal allowlist precedes advertising rules');
check($customConfig['dns']['nameserver-policy']['+.blocked.example'] === ['https://1.1.1.1/dns-query#PROXY'], 'Personal proxy exceptions use proxy DNS');
$bad = $settings;
$bad['nodes'][] = $bad['nodes'][0];
expectInvalid(fn() => testConfig($bad), 'Duplicate node names fail validation');
$bad = $settings;
$bad['nodes'][0]['title'] = 'AUTO';
expectInvalid(fn() => testConfig($bad), 'Reserved group names fail validation');
$bad = $settings;
$bad['direct_domains'] = ['example.com,PROXY'];
expectInvalid(fn() => testConfig($bad), 'Personal domain entries cannot inject extra routing fields');
$bad = $settings['nodes'][1];
$bad['password'] = 'not-an-authentication-uuid';
expectInvalid(fn() => convertNode($bad), 'Invalid VLESS authentication is rejected');
$bad = $settings['nodes'][1];
$bad['publicKey'] = 'broken';
expectInvalid(fn() => convertNode($bad), 'Invalid Reality public key is rejected');
$bad = $settings['nodes'][0];
$bad['port'] = '70000';
expectInvalid(fn() => convertNode($bad), 'Invalid ports are rejected');
$quoted = encodeYaml(['value' => "012345: #中文\n\"quoted\"", 'boolean' => false]);
check(str_contains($quoted, '"value": "012345: #中文\\n\\"quoted\\""') && str_contains($quoted, '"boolean": false'), 'YAML quotes punctuation, multiline strings and numbers stored as text');
require __DIR__ . '/rules.php';
echo "\n$passed checks passed. No real nodes or upstreams were contacted.\n";
