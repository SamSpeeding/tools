<?php
declare(strict_types=1);
require __DIR__.'/../../HongguoPHP/api.php';
function ordered(mixed $v): mixed {
    if(!is_array($v))return $v;
    $v=array_map('ordered',$v);if(!array_is_list($v))ksort($v);return $v;
}
function check(bool $ok,string $message): void {if(!$ok)throw new RuntimeException($message);}
$cases=json_decode(file_get_contents(__DIR__.'/private/replay-cases.json'),true,512,JSON_THROW_ON_ERROR);
$rows=[];
foreach($cases as $case){
    $raw=json_decode(file_get_contents($case['file']),true,512,JSON_THROW_ON_ERROR|JSON_BIGINT_AS_STRING);$calls=0;
    $response=hg_api_dispatch($case['input'],function($method,$path,$query=[], $body=null)use($case,$raw,&$calls){
        $calls++;check($method===$case['method']&&$path===$case['path'],$case['id'].' request method/path');
        unset($query['session_uuid']);
        check(ordered($query)===ordered($case['query']),$case['id'].' extra query');
        check(ordered($body)===ordered($case['body']),$case['id'].' request body');
        return $raw['response'];
    });
    check($calls===1,$case['id'].' one platform request');$expected=$case['expected'];
    if(isset($expected['series_ids']))check(array_column($response['items'],'series_id')===$expected['series_ids'],$case['id'].' normalized series IDs');
    if(isset($expected['selector_rows']))check(count($response['rows'])===$expected['selector_rows'],$case['id'].' filter rows');
    if(isset($expected['episodes']))check(count($response['episodes'])===$expected['episodes']&&$response['complete'],$case['id'].' episode completeness');
    if(array_key_exists('has_more',$expected))check($response['has_more']===$expected['has_more'],$case['id'].' pagination');
    $rows[]=['id'=>$case['id'],'passed'=>true];
}
echo json_encode(['passed'=>true,'replayed_requests'=>count($rows),'checks'=>$rows],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE),PHP_EOL;
