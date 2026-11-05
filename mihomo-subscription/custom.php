<?php
declare(strict_types=1);

// 日常自定义配置写在这里；重新运行打包脚本并确认发布后，路由器需重新获取并加载。
// 以下除订阅服务域名外都是注释示例，去掉对应行的 // 即可启用。
return [
    // 域名后缀：包含其子域名；不要填写 https://、路径、端口或通配符。
    // 直连、代理、屏蔽按此顺序匹配，避免在多个列表里填写同一域名。
    'direct_domains' => [
        'tools.sangonsek.com', // 获取订阅无需先连上代理。
        // 'example.cn',
    ],
    'proxy_domains' => [
        // 'example.com',
    ],
    'reject_domains' => [
        // 'ads.example.com',
    ],

    // 原生 mihomo 规则：位于私有网络和上面个人域名规则之后、社区规则之前。
    // 按顺序匹配；不要随意添加 MATCH，否则后面的社区规则不会再匹配。
    'rules' => [
        // 'DOMAIN-KEYWORD,example,PROXY',
        // 'IP-CIDR,203.0.113.7/32,PROXY,no-resolve',
    ],

    // 自定义 DNS 映射；如需指定直连/代理，同时配置上面的域名列表。
    'hosts' => [
        // 'nas.home.arpa' => '192.168.31.100',
        // 'service.example.com' => ['192.168.31.101', '192.168.31.102'],
    ],

    // 可选的原生 mihomo 配置，例如 DNS、端口、日志或 TUN。
    // 键值映射递归合并，列表整体替换，标量覆盖；不要在此覆盖核心字段：
    // proxies/proxy-groups/rule-providers/rules/hosts。
    // 节点在 config.php 中维护，个人规则和 hosts 使用上方专用字段。
    // ShellCrash 仍可能根据路由器运行模式调整入站和 DNS 设置。
    'overrides' => [
        // 'log-level' => 'warning',
        // 'dns' => [
        //     'nameserver-policy' => [
        //         '+.internal.example.com' => ['192.168.31.1'],
        //     ],
        // ],
    ],
];
