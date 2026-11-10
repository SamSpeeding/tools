<?php
declare(strict_types=1);
require __DIR__.'/../../HongguoPHP/play.php';
$checks=0;
function check(bool $ok,string $name):void {global $checks;if(!$ok)throw new RuntimeException($name);$checks++;}
$vectors=json_decode(file_get_contents(__DIR__.'/../../HongguoDesktop/tests/fixtures/hm-v3-vectors.json'),true,512,JSON_THROW_ON_ERROR);
foreach($vectors['cases'] as $i=>$v)check(hg_hm($v['url'],$v['body'],$v['khronos'],$v['entropy'])===$v['headers'],"H/M vector $i");
$gorgon=json_decode(file_get_contents(__DIR__.'/gorgon-vectors.json'),true,512,JSON_THROW_ON_ERROR);
foreach($gorgon['cases'] as $v)check(hg_gorgon($v['query'],$v['body'],$v['ts'],$v['nonce'])===$v['expected'],'Gorgon golden vector');
foreach(['abc'=>'66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0',str_repeat('abcd',16)=>'debe9ff92275b8a138604889c18e5a4d6fdb70e5387e5765293dcba39c0c5732'] as $in=>$want)check(bin2hex(hg_sm3($in))===$want,'SM3');
$truth=[
 ['93bc1df253ba1bf7618b19c448b806f64d810afc45b715fe5eb925f26cbf12f541ba098282','287216bfa89e662a0f748120c305e199'],
 ['a1bc2ff164b91df04dbf00f17dba00f47cbb35c27b922aec67a628eb52972fdc7ea036a7a7','d742b28967e4e6c92b699f4375add27f'],
 ['9cbc12fb588721cd69b739f977b70be7429c08e074990ec847843dcc738638cf76b33ebcbc','113fb30d9767d80e3edbb905b052204f'],
 ['a3bc2df760ba2bc27b8b34c04a8907f557be19f249be35c748ba03f64fbc1ff161ba29a2a2','b5674a8384f25d757585dadf343274d5'],
 ['9cbc12f45aba11f76fb814f444bd15f459b225cb5e8c15dd459a0fd170ac0ad358aa108b8b','121846f9d5829130ebc0397023feaf8c']
];
foreach($truth as [$raw,$want])check(hg_unwrap(hex2bin($raw),0)===$want,'spade known answer');
foreach([[null,[0,99,false]],['bytes=10-20',[10,20,true]],['bytes=99-',[99,99,true]],['bytes=-7',[93,99,true]],['bytes=-900',[0,99,true]],['bytes=5-999',[5,99,true]]] as [$in,$want])check(hg_range($in,100)===$want,'Range');
foreach(['bytes=','bytes=-0','bytes=101-','bytes=2-1','bytes=0-1,4-7','items=1-2'] as $bad) {
    try{hg_range($bad,100);check(false,'must reject bad range');}catch(RangeException){$checks++;}
}
// NIST SP 800-38A AES-CTR known answer; exercises crossing 0xff with the counter.
$key=hex2bin('2b7e151628aed2a6abf7158809cf4f3c');$iv=hex2bin('f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff');
$cipher=hex2bin('874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff');
$plain=hex2bin('6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51');
for($skip=0;$skip<32;$skip++) {
    $pad=$skip%16;$input=str_repeat("\0",$pad).substr($cipher,$skip);
    $got=openssl_decrypt($input,'aes-128-ctr',$key,OPENSSL_RAW_DATA,hg_counter($iv,intdiv($skip,16)));
    check(substr($got,$pad)===substr($plain,$skip),"CTR offset $skip");
}
foreach(['','123456789','not_a_vid',['123']] as $bad){try{hg_vid($bad);check(false,'bad vid');}catch(InvalidArgumentException){$checks++;}}
echo json_encode(['checks'=>$checks,'passed'=>true,'hm_vectors'=>64],JSON_PRETTY_PRINT),PHP_EOL;
