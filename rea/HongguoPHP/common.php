<?php
declare(strict_types=1);
/**
 * PHP 公共签名、设备档案与平台 HTTP 请求，PHP 8.1+（64 位），需要 curl、zlib。
 * 启动：php -S 127.0.0.1:8080 -t /path/to/HongguoPHP
 * 不调用 Python / Java / JAR / 原 SO / FFI / 签名服务，不写任何运行文件。
 * 固定设备与 App 请求档案沿用已验证配置；每次重新签名，绝不随机换 DID。
 * 已验证找剧、详情和单视频模型；不提供批量视频模型或完整原 JAR 算法。
 * x-argus/x-ladon 是参考组合中的时间戳编码，不是原算法完整复刻。
 * 2026-10-14：H/M 移植自本项目审计过的 v3 算法；大表是数据，不是代码。
 */

function hg_u32(int $v): int { return $v & 0xffffffff; }
function hg_rol32(int $v, int $n): int {
    $v &= 0xffffffff; $n &= 31;
    return $n === 0 ? $v : (($v << $n) | ($v >> (32 - $n))) & 0xffffffff;
}
function hg_ror32(int $v, int $n): int { return hg_rol32($v, (32 - ($n & 31)) & 31); }
function hg_sr64(int $v, int $n): int {
    return $n === 0 ? $v : (($v >> $n) & (PHP_INT_MAX >> ($n - 1)));
}
function hg_ror64(int $v, int $n): int {
    $n &= 63;
    return $n === 0 ? $v : hg_sr64($v, $n) | ($v << (64 - $n));
}
function hg_add64(int $a, int $b): int {
    // PHP 的溢出加法会变成浮点数，必须用高低 32 位实现模 2^64 加法。
    $low = ($a & 0xffffffff) + ($b & 0xffffffff);
    $high = (hg_sr64($a, 32) + hg_sr64($b, 32) + ($low >> 32)) & 0xffffffff;
    return ($high << 32) | ($low & 0xffffffff);
}
function hg_i64(string $hex): int { return unpack('J', hex2bin($hex))[1]; }
function hg_bytes(string $s): array { return $s === '' ? [] : array_values(unpack('C*', $s)); }
function hg_binary(array $a): string { return $a === [] ? '' : pack('C*', ...$a); }
function hg_rl8(int $v, int $n): int { return (($v << $n) | ($v >> (8 - $n))) & 255; }

function hg_sm3(string $data): string {
    $bits = strlen($data) * 8;
    $data .= "\x80";
    $data .= str_repeat("\0", (56 - strlen($data) % 64 + 64) % 64) . pack('J', $bits);
    $iv = [0x7380166f,0x4914b2b9,0x172442d7,0xda8a0600,0xa96f30bc,0x163138aa,0xe38dee4d,0xb0fb0e4e];
    for ($offset=0; $offset<strlen($data); $offset+=64) {
        $w = array_values(unpack('N16', substr($data,$offset,64)));
        for ($j=16;$j<68;$j++) {
            $x=$w[$j-16]^$w[$j-9]^hg_rol32($w[$j-3],15);
            $w[]=hg_u32($x^hg_rol32($x,15)^hg_rol32($x,23)^hg_rol32($w[$j-13],7)^$w[$j-6]);
        }
        [$a,$b,$c,$d,$e,$f,$g,$h]=$iv;
        for($j=0;$j<64;$j++) {
            $ss1=hg_rol32(hg_u32(hg_rol32($a,12)+$e+hg_rol32($j<16?0x79cc4519:0x7a879d8a,$j%32)),7);
            $ss2=$ss1^hg_rol32($a,12);
            $ff=$j<16?($a^$b^$c):(($a&$b)|($a&$c)|($b&$c));
            $gg=$j<16?($e^$f^$g):(($e&$f)|((~$e)&$g));
            $t1=hg_u32($ff+$d+$ss2+($w[$j]^$w[$j+4]));
            $t2=hg_u32($gg+$h+$ss1+$w[$j]);
            [$d,$c,$b,$a]=[$c,hg_rol32($b,9),$a,$t1];
            [$h,$g,$f,$e]=[$g,hg_rol32($f,19),$e,hg_u32($t2^hg_rol32($t2,9)^hg_rol32($t2,17))];
        }
        foreach ([$a,$b,$c,$d,$e,$f,$g,$h] as $i=>$value) $iv[$i]^=$value;
    }
    return pack('N*',...$iv);
}
function hg_checksum(string $data): int {
    $sum=0x20220420;
    for($i=0;$i<12;$i++) {
        if(($i&1)===0) {$temp=($sum>>3)^$sum;$sum=ord($data[$i])^($sum<<7);}
        else {$temp=($sum>>5)^$sum;$sum=(ord($data[$i])|($sum<<11))^0xffffffff;}
        $sum=($sum^$temp)&0xffffffff;
    }
    return ($sum|4)^0x1000000;
}
function hg_iv(int $iv,string $data): int {
    foreach(hg_bytes($data) as $i=>$byte) {
        $iv=(($i&1)===0 ? (($iv>>4)^$iv^($iv<<6)^$byte) : ~(($iv>>7)^$iv^($byte|($iv<<12))))&0xffffffff;
    }
    return $iv;
}
function hg_f13(string $q,string $body,int $ts): string {
    $time=pack('V',$ts);$iv=hg_iv(hg_iv(hg_iv(0x20230928,$q),$body),$time);
    $selector=(($iv&15)*171)>>9;
    return match(($iv&15)-(($selector*3)&255)) {
        0=>hg_branch0($selector,$ts,$q.$body.$time),
        1=>hg_branch1($selector,$ts,$q.$body.$time),
        2=>hg_branch2($iv,$ts,$q.$body.$time),
    };
}
function hg_branch0(int $selector,int $ts,string $data): string {
    $base=[0xc4a78580,0xb3c0fd39,0xc58c5686,0xc9aa3ba7,0xf5a7adf2,0x963c2ed1][$selector];
    $rotation=($base+$ts+1)&255;$count=($base+$ts)&0xffffffff;
    $constants=array_map(fn($v)=>hg_ror32($v,$rotation), HG_BRANCH0_CONSTANTS);
    $pad='';foreach([0xfa,0x45,0x61,0xd7] as $b) $pad.=chr((($b|($b<<8))>>(($count+2)&7))&255);
    $di=array_values(unpack('N*',$data.$pad.hex2bin('00000000000001a0')));
    $initial=array_map(fn($v)=>hg_ror32($v,$count&255),[0x7aba4fc8,0x67166507,0x6403fa00,0x340f512f,984304912,3005047866,2874125293,2152413264]);
    $d0=$di[0];
    for($i=0;$i<112;$i++) {
        $d1=$di[$i+1];$d14=$di[$i+14];
        $r1=hg_rol32($d1,14)^hg_rol32($d1,25)^($d1>>3);
        $r2=hg_rol32($d14,13)^hg_rol32($d14,15)^($d14>>10);
        $di[]=hg_u32($d0+$di[$i+9]+$r1+$r2);$d0=$d1;
    }
    [$rounds,$x1,$x2,$x3,$x4,$x5,$x6,$x7,$x8,$x9,$x10]=[
        [101,5,7,6,3,2,1,0,5,4,3],[96,0,6,7,5,3,2,1,5,4,4],
        [96,7,6,2,1,4,0,5,4,3,5],[99,3,6,2,4,5,1,0,0,7,6],
        [96,0,5,6,7,3,1,2,5,4,4],[100,2,0,3,5,4,6,7,2,1,5]][$selector];
    $d=$initial;
    for($i=0;$i<$rounds;$i++) {
        $offset=$base+$i;$n0=$di[$offset&127];
        $n1=(($d[$x3]^$d[$x4])&$d[$x1])^$d[$x3];
        $n2=hg_rol32($d[$x1],26)^hg_rol32($d[$x1],21)^hg_rol32($d[$x1],7);
        $n4=hg_u32($n0+$n1+$n2+$constants[$offset&63]+$d[$x5]);
        $n5=hg_rol32($d[$x2],30)^hg_rol32($d[$x2],19)^hg_rol32($d[$x2],10);
        $n6=($d[$x2]&$d[$x6])|(($d[$x2]|$d[$x6])&$d[$x7]);$old=$d[$x9];
        $d=[$d[7],$d[0],$d[1],$d[2],$d[3],$d[4],$d[5],$d[6]];
        $d[$x10]=hg_u32($n5+$n6+$n4);$d[$x8]=hg_u32($old+$n4);
    }
    $ret='';foreach($d as $i=>$v)$ret.=pack('N',hg_u32($v+$initial[$i]));
    $ret=substr($ret,0,16)^substr($ret,16);
    return $ret.pack('V',hg_checksum($ret));
}
function hg_table(): string {
    static $table=null;
    if($table===null) {
        $table=gzuncompress(base64_decode(HG_TABLE_ZLIB,true),81936);
        if($table===false || strlen($table)!==81936 || hash('sha256',$table)!=='239ddf955d14a008311b8c3adcf05713b858954068fff02ab19c2ba81e31d1d3')
            throw new RuntimeException('Medusa 查找表损坏');
    }
    return $table;
}
function hg_r00(array $state,int $extra,string $table,int $offset): int {
    $indices=[8*hg_sr64($state[0],56), (hg_sr64($state[1],45)&2040)+2048,
        (hg_sr64($state[2],37)&2040)+4096,(hg_sr64($state[3],29)&2040)+6144,
        (hg_sr64($state[4],21)&2040)+8192,(hg_sr64($state[5],13)&2040)+10240,
        8*(hg_sr64($state[6],8)&255)+12288,8*($state[7]&255)+14336];
    $value=$extra;
    foreach($indices as $index)$value^=unpack('P',substr($table,$offset+$index,8))[1];
    return $value;
}
function hg_swap(array $src,array $xor,array $constants,string $table,int $offset,array $order,?array $typ=null): array {
    $state=[];for($i=0;$i<8;$i++)$state[]=$src[$order[$i]]^$xor[$i];$key=$xor;
    for($round=0;$round<10;$round++) {
        $next=[];for($i=0;$i<8;$i++)$next[]=hg_r00(array_merge(array_slice($key,$i),array_slice($key,0,$i)),0,$table,$offset);
        $key=$next;$key[7]^=$constants[$round+1];
        $next=[];for($i=0;$i<8;$i++)$next[]=hg_r00(array_merge(array_slice($state,$i),array_slice($state,0,$i)),$key[$i],$table,$offset);
        $state=$next;
    }
    $result=[];
    for($i=0;$i<8;$i++)$result[]=$typ===null ? ($state[(8-$i)%8]^$xor[$i]^$src[$i]) : ($state[7-$i]^$typ[($i+1)%8]);
    if($typ!==null)$result[6]^=$src[7];
    return $result;
}
function hg_branch1(int $selector,int $ts,string $data): string {
    $base=[0x808a9c79,0xf079807e,0xbadf79c5,0xa785d3ff,0x82d8438c][$selector];
    $seed=hg_ror64($ts,($base+$ts)&255);$rotation=($base+$ts+1)&63;
    $order=[[5,7,1,2,4,0,6,3],[0,5,2,4,1,3,7,6],[5,7,2,4,1,6,3,0],[3,0,2,4,6,7,1,5],[4,5,0,3,6,2,1,7]][$selector];
    $constants=array_map(fn($v)=>hg_ror64(hg_i64($v),$rotation),[
        '87aeea5dab37cd6b','7ff48becb4f54087','b0724c06706bbd5d','1fe5dfb1143e328d',
        '1a2331d00af4f1f2','caff7131bb1e71ba','33385e1042752218','ff01ed65d4a441fb',
        '0adb1ec8828c80e8','62475d12f4e06fe7','00bd0b238da4fe72']);
    $src=array_values(unpack('J*',$data."\x80".str_repeat("\0",11)));
    $table=hg_table();$offset=$selector<<14;
    $swap=hg_swap($src,array_fill(0,8,$seed),$constants,$table,$offset,$order);
    $src=array_fill(0,8,0);$src[7]=416;
    $xor=[$swap[4],$swap[3],$swap[2],$swap[1],$swap[0],$swap[7],$swap[6],$swap[5]];
    $swap=hg_swap($src,$xor,$constants,$table,$offset,$order,$swap);
    $ret='';for($i=7;$i>=0;$i--){$p=pack('P',$swap[$i]);$ret.=$p[1].$p[3].$p[5].$p[6];}
    $ret=substr($ret,0,16)^substr($ret,16);
    return $ret.pack('V',hg_checksum($ret));
}
function hg_branch2(int $iv,int $ts,string $data): string {
    // Preserve the audited operator grouping: iv & (15 - 2).
    $n=($iv&13)*86;$selector=(($n>>15)&255)+(($n>>8)&255);
    $base=[0x8980f29b,0xeb549c7f,0xb08726db,0xd40cb5e6,0xe8f559e4][$selector];
    $count=hg_u32($base+$ts);$rotation=($base+$ts+1)&255;
    $pad='';foreach([0x84,0x96,0x77,0x9d,0xd4,0x15,0x0b,0xf8] as $b)$pad.=chr((($b|($b<<8))>>(($count+5)&7))&255);
    $words=array_values(unpack('V*',$data.$pad.hex2bin('a0010000')));
    $orders=hg_bytes(substr(hex2bin(HG_BRANCH2_ORDERS),$selector*64,64));
    $constants=array_map(fn($v)=>hg_ror32($v,$rotation),HG_SV2);
    $start=array_map(fn($v)=>hg_ror32($v,$count&255),[0x79e0f2fb,0xc8b52570,0xebc2f8cd,0x7c104d93]);
    $end=array_map(fn($v)=>hg_ror32($v,($count+6)&255),[0x19be4866,0xe85986b4,0xe19b326e,0x71d1d7d4]);
    $shifts=[[7,12,17,22],[5,9,14,20],[4,11,16,23],[6,10,15,21]];[$a,$b,$c,$d]=$start;
    for($i=0;$i<64;$i++) {
        $r=intdiv($i,16);
        $mixed=match($r){0=>($b&$c)|(~$b&$d),1=>($b&$d)|($c&~$d),2=>$b^$c^$d,3=>($c^($b|~$d))&0xffffffff};
        $value=hg_u32($a+$mixed+$words[$orders[$i]]+$constants[$i]);
        [$a,$b,$c,$d]=[$d,$b+hg_rol32($value,$shifts[$r][$i%4]),$b,$c];
    }
    $ret='';foreach([$a,$b,$c,$d] as $i=>$v)$ret.=pack('V',hg_u32($start[$i]+$v)^$end[$i]);
    return $ret.pack('V',hg_checksum($ret));
}
function hg_xtime(int $v): int { return (($v<<1)^(($v&128)?0x1b:0))&255; }
function hg_aesBlock(string $data,array $key,array $sbox,array $con,array $order): string {
    $s=hg_bytes($data);
    $add=function(int $offset,bool $permuted)use(&$s,$key,$con):void{
        for($i=0;$i<4;$i++)for($j=0;$j<4;$j++)$s[4*$i+$j]^=$key[$offset+4*$i+($permuted?$con[$j]:$j)];
    };
    $add(0,true);
    for($round=1;$round<=2;$round++) {
        $s=array_map(fn($v)=>$sbox[$v],$s);$old=$s;
        for($i=0;$i<4;$i++)for($j=0;$j<4;$j++)$s[4*$i+$j]=$old[4*$con[$i]+$j];
        $old=$s;foreach($order as $i=>$j)$s[$i]=$old[$j];
        if($round===1) {
            $old=$s;for($i=0;$i<4;$i++)for($j=0;$j<4;$j++)$s[4*$i+$j]=$old[4*$i+$con[$j]];
            for($i=0;$i<4;$i++) {
                $t=$s[$i]^$s[4+$i]^$s[8+$i]^$s[12+$i];$u=$s[$i];
                $s[$i]^=$t^hg_xtime($s[$i]^$s[4+$i]);$s[4+$i]^=$t^hg_xtime($s[4+$i]^$s[8+$i]);
                $s[8+$i]^=$t^hg_xtime($s[8+$i]^$s[12+$i]);$s[12+$i]^=$t^hg_xtime($s[12+$i]^$u);
            }
        }
        $add($round*16,true);
    }
    $add(16,false);return hg_binary($s);
}
function hg_aesV3(string $data,int $ts): string {
    $mode=$ts&3;$sbox=hg_bytes(substr(hex2bin(HG_SBOX),$mode*256,256));
    $initial=[0xca025ddc,0x823dc546,0xc9420583,0xc298225f][$mode];
    $mk=hg_bytes(str_repeat(pack('V',$initial),4)^hex2bin('f1593376766ea98d34f31b057a9d5be4'));
    $mk=array_merge($mk,array_fill(0,32,0));$rounds=8;
    for($i=4;$i<12;$i++) {
        $idx=4*($i-1);[$k0,$k1,$k2,$k3]=array_slice($mk,$idx,4);
        if(($i&3)===0)[$k0,$k1,$k2,$k3]=[(($initial>>($rounds&24))^$sbox[$k1])&255,$sbox[$k2],$sbox[$k3],$sbox[$k0]];
        $rounds+=2;foreach([$k0,$k1,$k2,$k3] as $j=>$v)$mk[$idx+4+$j]=$v^$mk[$idx-12+$j];
    }
    $con=[[1,0,2,3],[2,0,3,1],[0,1,3,2],[1,0,2,3]][$mode];
    $order=[[0,9,14,11,4,13,2,7,8,1,6,15,12,5,10,3],[0,9,14,15,4,13,2,7,8,1,6,3,12,5,10,11],
            [0,9,14,7,4,13,2,11,8,1,6,3,12,5,10,15],[0,9,14,11,4,13,2,7,8,1,6,15,12,5,10,3]][$mode];
    $bytes=hg_bytes($data);$plain=[];
    if(count($bytes)<248)throw new RuntimeException('Medusa 内文过短');
    for($i=0;$i<31;$i++) {
        $p=$i*8;$plain[]=(($bytes[$p]>>4&2)|($bytes[$p+1]&64)|($bytes[$p+2]>>2&1)|($bytes[$p+3]<<3&-128)|
            ($bytes[$p+4]>>1&4)|($bytes[$p+5]<<3&16)|($bytes[$p+6]<<5&32)|($bytes[$p+7]>>4&8))&255;
    }
    $plain[]=1;$plain=hg_binary($plain);$previous=hex2bin('1fe109a4125283f418de9e051a969e12');$key='';
    for($i=0;$i<32;$i+=16){$previous=hg_aesBlock(substr($plain,$i,16)^$previous,$mk,$sbox,$con,$order);$key.=$previous;}
    for($i=0;$i<31;$i++) {
        $k=ord($key[$i]);$p=$i*8;
        $bytes[$p]=($bytes[$p]&-33)|(($k<<4)&32);$bytes[$p+1]=($bytes[$p+1]&-65)|($k&64);
        $bytes[$p+2]=($bytes[$p+2]&-5)|(($k*4)&4);$bytes[$p+3]=($bytes[$p+3]&-17)|(($k>>3)&16);
        $bytes[$p+4]=($bytes[$p+4]&-9)|(($k+$k)&8);$bytes[$p+5]=($bytes[$p+5]&-3)|(($k>>3)&2);
        $bytes[$p+6]=($bytes[$p+6]&-2)|(($k>>5)&1);$bytes[$p+7]=($bytes[$p+7]&127)|(($k<<4)&128);
    }
    return $key[31].hg_binary($bytes);
}
function hg_helios(int $ts,int $nonce): string {
    $prefix=pack('V',$nonce);$key=md5($prefix.'8662');$words=array_values(unpack('P4',$key));
    $schedule=[$words[0]];[$left,$right]=array_slice($words,0,2);$pending=array_slice($words,2);
    for($i=0;$i<34;$i++){$mixed=hg_add64(hg_ror64($right,8),$left)^$i;$pending[]=$mixed;$left=$mixed^hg_ror64($left,61);$schedule[]=$left;$right=array_shift($pending);}
    $raw="$ts-1588093228-8662";$pad=16-strlen($raw)%16;$raw.=str_repeat(chr($pad),$pad);$out=$prefix;
    for($i=0;$i<strlen($raw);$i+=16){[$left,$right]=array_values(unpack('P2',substr($raw,$i,16)));
        for($j=0;$j<34;$j++){$right=$schedule[$j]^hg_add64($left,hg_ror64($right,8));$left=$right^hg_ror64($left,61);}
        $out.=pack('P2',$left,$right);
    }
    return base64_encode($out);
}
function hg_varint(int $v): string {$out='';while($v>127){$out.=chr(($v&127)|128);$v>>=7;}return $out.chr($v);}
function hg_proto(array $fields): string {
    $out='';foreach($fields as [$field,$value]) {
        if($value===null||$value===''||$value===0||$value===0.0)continue;
        if(is_int($value))$out.=hg_varint($field<<3).hg_varint($value>=0?$value<<1:~($value<<1));
        elseif(is_float($value))$out.=hg_varint(($field<<3)|5).pack('g',$value);
        else $out.=hg_varint(($field<<3)|2).hg_varint(strlen($value)).$value;
    }return $out;
}
function hg_environment(array $q,int $ts,array $e): string {
    $model=$q['device_type']??'';$brand=$q['device_brand']??'';$sample=1728388016635;
    $device=hg_proto([[1,1],[2,2],[3,'8662'],[4,$q['device_id']],[6,'!noperm!'],[7,-888888],[8,-888888],[9,3],[10,-888888],
        [11,'!notset!'],[12,'Asia/Shanghai,8'],[13,'zh_CN'],[14,4],[16,255.24993896484375],[17,35.58599090576172],
        [18,3.467449188232422],[19,3.467449188232422],[20,255.1754913330078],[21,42.17544174194336],
        [22,$q['os_version']??''],[23,41],[24,36],[25,$sample],[26,$sample],[27,$sample],[28,$sample+2],
        [29,-1],[30,$model],[31,$brand],[32,$model],[33,$model],[34,$brand],[35,$brand],[36,$brand],[38,31]]);
    return hg_proto([[1,$e[2]],[2,146331399],[3,146331396],[5,7],[6,'v04.06.04.03-bugfix'],[7,$e[3]],[12,$device],
        [13,hg_proto([[1,$ts],[2,-2],[4,200]])],[14,$q['version_name']]]);
}
function hg_mix(string $raw,string $key): string {
    $bytes=hg_bytes($raw);$value=array_fill(0,count($bytes),0);$n=count($bytes);
    foreach($bytes as $i=>$v){$offset=($i*4)&28;$a=ord($key[$offset]);$b=ord($key[$offset+1]);
        $v=(hg_rl8($v,4)+$a)^$b;$v=hg_rl8((~$v)&255,3);$v=(($v+$b)&255)^$a;$value[$n-$i-1]=(~$v)&255;}
    $flag=$value[$n-1]^$value[$n-2];$initial=$value[0];$value[0]=(~$flag+$value[0])&255;
    $value[1]=(($value[0]^$value[$n-1]^254)+$value[1])&255;
    $value[2]=($value[2]+(($flag-$initial)^hg_rl8($value[1],3)^2))&255;
    for($i=0;$i<$n-4;$i++){$mask=hg_rl8($value[$i+2],3)^$value[$i+1]^($i+3);$value[$i+3]=(~$mask+$value[$i+3])&255;}
    $value[$n-1]^=$value[$n-2];$value[0]=(($value[0]^$value[1])+array_sum(array_slice($value,1)))&255;
    return hg_binary($value);
}
function hg_hm(string $url,string $body,int $ts,?array $entropy=null): array {
    if(PHP_INT_SIZE!==8)throw new RuntimeException('需要 64 位 PHP');
    $rawQuery=parse_url($url,PHP_URL_QUERY)??'';parse_str($rawQuery,$q);
    if(($q['aid']??'')!=='8662'||empty($q['device_id'])||empty($q['version_name']))throw new RuntimeException('签名请求档案不完整');
    $e=$entropy??[random_int(0,0xffffffff),random_int(0,0xffffffff),random_int(100,120),random_int(10001,12000),random_int(0,0xffffffff),random_int(0,0xffffffff)];
    $qhash=hg_sm3($rawQuery);$bhash=$body===''?str_repeat("\0",16):md5($body,true);$binding=hg_f13($qhash,$bhash,$ts);
    $magic=hex2bin('f7e85ffad7d7dc3bd62ac87057cf6118');$seed=pack('P',320);
    $proto=hg_proto([[1,$magic],[2,3],[3,$e[1]],[4,'8662'],[5,$q['device_id']],[6,'1588093228'],[7,$q['version_name']],
        [8,'v04.06.04-ml-android'],[9,67503104],[10,$seed],[12,$ts],[13,$binding],[14,substr($qhash,0,6)],
        [15,hg_proto([[1,111],[2,10],[3,694367],[5,586952199]])],[17,$ts],[19,hg_sm3($rawQuery.$bhash.'none')],
        [20,'none'],[21,312],[23,hg_environment($q,$ts,$e)],[24,'{"cmr":16777216,"cmr2":16777216,"un_h":1879194040,"vpn":0,"kd":0,"fkd":3672518972,"pd":-1872573247,"dyn":"","do":0,"tk":true}']]);
    $signKey=hex2bin('8ebdfa3806ecc5cee79423e6029ed82540bc2218bb7eaef71cb691f7aa8aa2f5');
    $nonce=pack('V',$e[4]);$key=hg_sm3($signKey.$nonce.$signKey);
    $d1=($e[4]>>16)&255;$d2=(($d1<<11)|($e[4]>>24))^($d1>>5)^$d1;$mixSeed=pack('V',(~$d2)&0xffffffff);
    $mixed=strrev($seed.hg_mix($proto,$key));for($i=0;$i<strlen($mixed);$i++)$mixed[$i]=chr(ord($mixed[$i])^ord($mixSeed[(~$i)&3]));
    $check=((ord($qhash[0])&63)<<14)|0x18000001|((ord($binding[0])&63)<<8);
    $inner="\x35".pack('V2',$e[5],$check).$mixed.substr($nonce,2);
    $version=pack('V',3).$magic;$envelope='';foreach(unpack('V*',$version) as $v)$envelope.=pack('V',$v^$ts);
    $medusa=base64_encode($envelope.substr($nonce,0,2)."\x00\x01".hg_aesV3($inner,$ts));
    return ['x-helios'=>hg_helios($ts,$e[0]),'x-medusa'=>$medusa];
}
function hg_gorgon(string $query,string $body,int $ts,int $nonce): string {
    $raw=substr(md5($query,true),0,4).($body===''?str_repeat("\0",4):substr(md5($body,true),0,4)).str_repeat("\0",4).pack('V',67503104).pack('N',$ts);
    $key=[0x4a,0x40,0x16,($nonce>>8)&255,0x47,0x6c,1,$nonce&255];$table=range(0,255);$j=0;
    // 此协议的 RC4 变体在两个阶段都只覆盖 S[i]，不是标准 RC4 的交换。
    for($i=0;$i<256;$i++){$j=($j+$table[$i]+$key[$i%8])%256;$table[$i]=$table[$j];}
    $i=$j=0;$result=[];
    foreach(hg_bytes($raw) as $v){$i=($i+1)&255;$j=($j+$table[$i])&255;$y=$table[$j];$table[$i]=$y;$result[]=$v^$table[($y+$y)&255];}
    foreach($result as $i=>$v){$v=(($v>>4)|($v<<4))&255;$following=$result[$i+1]??$result[0];$x=$following^$v;$reverse=0;
        for($b=0;$b<8;$b++)$reverse=($reverse<<1)|(($x>>$b)&1);$result[$i]=(~($reverse^20))&255;}
    return bin2hex("\x84\x04".pack('v2',$nonce,320).hg_binary($result));
}

const HG_SBOX = 'fa7d086b9c59b34b045f39d0384a91990067a6209ff54d827326eedf18668333800319fbd9feaeaaa9b052c60bf379254e78b436ac5d1a279e88dbbd3c63ec4915c1301fdcb856d46ccdca0943c835a3ef1ef496d2fc0e727b9484d1ea455a62023fd31281342bdd7ee628f2a54613013b21f66137292a0ded8cafbf9d5cbb24760f75e45389e1988db19a65704f544c58ab6e6f8b23c407110cbacfa0a48ed8053d14b2da74c3d7e7bed67fde48163e8590a155b7774222c986502e17f964312c9bf16d1c4468e3e9a89397cb3257ebe5716aadc0ccc7c5fd601da22d47a7e251695e7ace0a41b6958ff7b987e03a06108ab5f85bd5f0bc92ff7c2fc2e81b40ec1bdabdba98910cb22b83413467fb0ad876b546055961237590872ae350154cacb179ebaee595470468f0863d518b0fca8ee4b94ef21282bc0ed5f7ef2825cf5b5de96a5502e133be93e7f5ad9d3e3924a8e2fa1757d07a0d0830d6b8a38dfd079ac41e6e226497d21db0bf45663f6cdddb2780a711dca6c552f8c0b6c85c0073607ba01913aac935484bd3a4cd9f99f3104440547e29f4061fa2aba12f3cf6af856236217f5edf201ab3b4e6ff72848f6526945a77ea4378c74acc2c146bc6e87453fcd41cce317003188c96383289f13a5fd7f9a969b7633758c23bc371cb9e92018a0b4d889bbb4f6d6fe0fea549de561609ed9cc12dee817dd97cd12e425b4dc1a65dea44fd454e1ba13fd189e17d2faadbabad59cbb1ce9a28c9e0f670394ad7ff30f5ddbc573b118db2ee00b6e61a5a7cf9dec4cd2e80bbb94ca59f8408c66f426cf027e78b3a9c51fb6721754131a7ca20432ab7bfd97af2b5f88c2c23834f8f60a004133714e301c563665c7481df58bd68903dd2b334f419933229d649ae0d4bd8079eac1e2d0b40b872ba761071a8e4561d48fee5c24791da87269d1f886bc098be25099733a385165e7fdc6e54e9f7a9c8e8c377d0822bec02628a920e3eb00f05f3f19678388636183c24cf0ab453cc6165a4c794d5157e6def792235126a8e5206557b46645095e20cedd31703a29b99eb1cfcafd47369fa5ff72c1ebfc8e1f39f76807148aa94ad64fb89c660c332b34dd2e044dd5fa8b1c7682334c96d127fb7eb15bea9d17893a00c92a4d747e38ac270ab26419a79a7d814858fc06f56d08c11b92e3ce29dcf0ede035d463ecd38430f335ad91a656c223bfc30a688ea37a2b48d8e519cd640eef9f884f4ae97e9ca0a456757042f835cd5c5c482b6a391981f4aac96816ecb1b0908af1895497d54edfa16313adab866f5a5f1fe10010674cc63df7c2825f6ceb24f8be5bc8769bb8621070036e70b50599b1ce862581961f2bd275eba1de699423d0d2ab5dc5b29f02d4c537b6a734e3f75ff4ba1351755723920d3b0fdef02ec777ee42bdb90c1059e7ad4526b2413';
const HG_BRANCH2_ORDERS = '0f0704000908030a060b050d0e010c020f05080c0009020103070e060b0a0d04060500070c000a04080f010b0d09020e060b02050403080101070a000d0c090e0d070e0f0b0208030c0509010004060a0d0902060f0b0a040807000c0503010e0c090f07060f030e020d0405010b0a000c050a090e0802040407030f01060b000b0f0408020a0700090d06010e03050c0b060a0508020c03070f0e090d0001040906080f050800040a0b030d01020c0e090d0c0604070a03030f00080105020e01000d0f090a0b0e0402080703060c0501080a0c0f0905060b000304020e070d04080f000c0f0e0d0a01060207090503040205080d0b0a0606000e0f070c09030a08040f000b01060d0c0709030e05020a070b050f00020e0108030d0c0609040d070f08050f06040b0a0e0c090002030d0c020704010b0e0e08060f09050003';
const HG_SV2 = [0xa7aefe20,0x7149f1d6,0x47e4ca07,0xe9b58f67,0x93b924de,0xc614d0f5,0x38afe0ef,0xb2bbad73,0xe24444c3,0x9d3aec9b,0xdf7b37e4,0xd8b16d40,0xf8ac31b8,0x76b9a90b,0x31d833ee,0x953fce64,0x353595a4,0x4609c13b,0x36925008,0x8c6d0925,0x5df5c177,0x1cfbf52b,0x8a4fa7f0,0x114ca35e,0x8193f984,0x7a7a8733,0x316ab4d5,0x3c20cfc9,0xa6d84453,0x3a18500c,0x798ec47a,0x97a76b28,0x66c4ff96,0x51716443,0xdd2fc3b,0xb5696da7,0xbbeb3ac5,0x5c53d204,0xd32608ce,0x7279b9ec,0xf4188ecf,0xf7d793db,0x332cc491,0xab76ae15,0x9bebe727,0x18a01384,0x5be9f8a7,0x5f90a754,0x39b663c0,0x36673c83,0x7c92f514,0x9d7d94d7,0xe2e8d9aa,0x5f7e9ea9,0x7abd4551,0x569e05da,0x40a25632,0x3df5a9a5,0xbab37d80,0x454286dc,0x3f5d4e78,0x3d7b75d,0xb1fe4af7,0xa5ab26a3];
const HG_BRANCH0_CONSTANTS = [0xebb64faf,0x7aadcc2,0xcf3187bf,0xe01138ff,0x6d0bfcff,0x5a30a3be,0xb41ad638,0x34180eb8,0xf233eb6f,0xb1a584cc,0xccc30dc7,0x47d1db51,0xd55653de,0x70a84fa1,0x57473c12,0xf76f0288,0x2c077f0a,0xda0dcad0,0xfbb86f6c,0xfdc4cf00,0x688a020d,0xe676c6a6,0x8cd6338b,0x1a3c8d0e,0xcce8b06b,0x6ad0ed0b,0xa0522717,0xdc71ac83,0x2285db71,0xd5b4dda6,0x736f8650,0x6560306c,0x617ce2a6,0xe423417e,0xa40e143,0x544e4032,0x88dffb2a,0x716c1ae0,0x4c467a88,0x5b23bb3,0xe1d0b866,0xbaa3dcb8,0xae3374d3,0xc3381a50,0x1702f75b,0xfe6da368,0xf0b4cf48,0x4e0ffbb8,0x72aad10d,0x26c53a3d,0xf2bce0f6,0xb4557581,0x4a257fdd,0x8c3182a2,0xab0b3b86,0x3d5dfb14,0x4f103634,0xd37b52d7,0x444eff16,0xeb0a33d1,0x6ca86f6e,0x284ba7,0x8387cfa,0x5fb37586];
const HG_TABLE_ZLIB =
    'eNoAIEDfv1e/EIu3nbBi+d24s0pHvuizvvlKuN3oR0ros7j5vkfdYaKBBDNFN9cEN2EzgaLXRYRKtOOY6v0R4/2EmLRKEergZ33kK9tCL+RC4Ct9Zy/bKy/k' .
    'feBC22d92yvg5C9nQn+1YAkyMImjCYl/MmC1ozAyowlgf4kwtYh3eJe6G0w3pXlQJZWkKnolKqWVUHl6pJV6JVClKqR5UKSVpSV6eSpxt60Pxkr3dA/3ccat' .
    't3RKxnQPrXH3SretSsZxD3S399fa12RteDXAVgVezt5Tv0rOv1beXgVKU95Kzl5Wv1MFw8fXbZOycrVtcsOT18e1spO1bdfDcrLH17KTw221x3IZbCyub7j0' .
    'ya70GW8sbMm4b8muLBn0uGwsuG8Zrsls9MqERfPaZaDZ86DK2kWE2WXa2fNFyqBlhEVl2srz2YSgnUFeChXnLbDQSD3MreF6Pcx60K09SD3hrT3MPdB64Ug7' .
    'Nmmz/mnxwLPxO/5pNsBp/sCzaTvxaTZpaf47s8A28ftAfXEZ0HN9SoKSLxQpg+svg0oUkoLrKRTrL5JKgymC4eaWYSDOIOFhIOEglubhziDhYZbhIM7mls4g' .
    '4WHh5iDo9cf1w/Exjw5xlbLeJfyMMdWMP3Pn7QU/7TFzjNUF57uT70NvQm1gQ227b++TYEJvYEPvu21Ck+9Cb7tDYJNteoQizYwabL3NbHqMIoS9Goy9zSJ6' .
    'bBqEIhqMes29hGyNPImgaCct/22hlwQ08ZNdBJNtNJehXfE0XQSXbZPxoYiNI5XfpHHDlXGI3yONw6Tfw5UjiHGkjSOk34iVw41x74CteJJ6Vy/tlGLjQgCC' .
    'AuOC7UJilAIAQgLjYu2CAJTX1qpSFekXItZ7WikjdkrOKUrWI1p7znYjzila1kp2e3wgxwjXW2svioY+tVMiLxm1L4pTPoYZIil1r7qoNa78AE8Hg0GM+SCD' .
    '+QBBB08gjEEggwcA+YxPB4xBAIMgT/lODDziaBfLvOLLTmg8DLwXaLziPE7LFww8F2hO4rwMy+A+rKHT7TQ7oTTg06w+O+3TO6Gs4DTtPqzt0+ChOz40JbrU' .
    'Yu00LbpiLSXt1Lq6NO26YtQlLTS61DTtJWK6ui2B78PCspmMYsKMgbLD72KZK+6gAQ0NKywBKysNoO4sDVjIyB2/HdkuHdlYv8jILh2/Lh3IWNkdyMgdv1gd' .
    'LsjZZhub06feo6PTo2anmxuj3rwADSdmrvl9J/m8Zg0Afa4VA1ibvTXpnJvpFb1YA5w1vZybWBXpNQNYNb0Vm5wD6bannxEkxfbeEfa2JJ+n3sUk3hGftvbF' .
    'p5/FJLYR3qf2iRQvF/EzpkAXponxLxRAM/FAFy+JpjMULzPxiRdAFKbgccEc/dzh5hzh4P3Bcebc/eYcweDh3HHB3P3gHOZx4Vc6M/Ec1HjV8XhXHDM61dQc' .
    '1fEzV3jUOjPUHFfx1Tp4CIhieS6LRsF5RgguYojBiy7BeWIIRouIo5fT1JgnlKcWjqSllGJShqVSFpSkjoZilIalpBZSYo6kYpQWpYaOUjZS6eQlv56t5J42' .
    'JelSrb9deBWRYYKMaJGMXWEVeGiCZSM8YStLPhg8X3BTVKF9aFN9PFRwX2ihVGhTcDx9oV8Fcj5TrHyVAFOVBaw+cgB8rABTPgWVfHIiqNTQongliXliDtwk' .
    'WZn/3Jl5JA5i/1kk/9wOeZlZYg5ZJHnc/2KZDiEVyoj36W/K6Q6IFSFv94hvyhUO6fchFfeIDspvIel6emQRKW9NxRFNeilkesVvKcURZHpNb3qhfmQAOKEA' .
    'iOwJtnqbFxeVehfsm7YJlRfh2BXMTWlzCaO5CEOdzSgGGXvTEHvkMac5VWO+vFJi9b5iObxjVfVSvPW+YzliUlVfvoV20Tnk7njFShsNSQdWjhCZ1V8JGyD0' .
    '8vQl/QEJZhDzPxB2mbTz/C+mf6rkEkF/Evyqpi9B5KpBf6b8EuQvME4M5qUc6ybm6zClDE4mHOwhsIIgcskRgsnsILAhEXKBcU9dX9paHl1agV9PcR7aXx5d' .
    'T4Fa2nFP2l+BXR5xWpJTQVvrA3jLW3iS60FTywPry1tBkngDU0ED65Jby1N4J12lAQGT1w0B1ycBpV0NkwENAaUn15NdpZMBJwENXdccLmzJvqgjSskjHL5s' .
    'LkqovkrJbBwjqC5sqL4cyUouIzi+Di/hiNugcn6r4Cm/rdWz7HHCOSUe7MIeszlx7OwlFqKcmbEr6LqZ6BaxnKK6K7G6mZwW6CuinCuxFpm6ougTe8iB7r9w' .
    'XWq7SK9aA17s8bKb6NNTP1DoP/HTm7JQUwpxYHKVjnSBcnQKlWBxgY6VgXJgCnSOcWCOlQpygXF0j7eefjCreD1+eI8wnrc9q0G88AsOCsu9C8tBDvC8vQrc' .
    'DKGrOm+nf6un3DqhDH9vOn+rodynbwyhbzrcq38Mp8xGhKWlMzSVju+OimAEdRgyjDAnU466hSe6MlMwjIWOfUmMnr1y+Kie+H29jEmoco0kGwIAsf7XAv6N' .
    'ABsk17E8V0B7yRfJqgYpfhInKnE8bcRmLkwZtYmnEn8zVZEYAZvbsFdLZYbfqQubUJQMbll6H5X5X213QPl3el+VH0BtNLrgr5qOCVGYaAcbQm0UCr9tyOaS' .
    'zS8Xah+YwUbXkuqA3z1VBJ85/tlwKHaw++WdRtd6uUgPFMv5eXLymnhRgQtEChIZwlV6dSjQMuqgVaUZtZHFt2raFS1pp07bDciCo1nffCXcbvQigpuwmUDR' .
    '6+sw0UCCmaKbsatfiMXbTlhuJfRZ3Hzfo/XxfkJMWqUI9Pxu3FmlI18IQiXacUz1/rOVF/I+cKHtmITEPxmw2lHRv1qwBBmYxBfwsz7ylW2hob7tFXDylzMb' .
    'xDu8S90Npm1yIfCVvrOXWpnRBLC/RJi8Sr0SqFIV0qWH+zjj1ls6urjb1gdjpXu90jyokkpSFRUo0srSEr08+1Yl47gHutvSEpXSSqg8PVtjuofWuHulKedf' .
    'K2+vAqXZNrnhyevjWtrh4+u2SVm54Gvta7I2vBoCbyVnL6vfqblr2cnhttpjJasCL2fvqV/jydq262E52ba3ZFeWDHpcsnlQZe0iwuxsZcKiee0y0OQMNhbX' .
    'N1z6ehbctwzXZDbQojJt5flsQlxX+ow3FrZkQu3s+SJl0DJwZj3o1h6knrTZ+B3/NBvg4B2btFn/tHjYziAvhYrzFqTWHuYeaL1w+LQ0/51ZYJseaKQe5tZw' .
    'vRt/4Nm0nfg0lJdBJQpJwfXnMJBwEEvzcPBwc8swEGeQvn2gvrgM6LlBivUXSaXBFBBLZ5DwsHBzdSVByReKlMFzkPAwy3AQZ4KYasafufP2oaG23bf3STCw' .
    '3cn3oTehNkf0+uP64fiY85/2mDnG6oK2d6G33SGwyUaHuEpZ7xJ+yTewoffdNqFCxt5mET02Da620EsCmvjJ/0aeRFC0k5ZePUKRZkYNtjYRDUa95l5CUJou' .
    'gsu2yfiNZjY9RhHCXniCyTaay9Cuxu/hyhHEONKBdkqxcSEAQZd3wFY8Sb2rYcTGkcpv0ri4EdJvxMrhxkohgXGxdkEA0so4xO+RxmGAccF2ITFKAbsUJesR' .
    'rT1nDEVDn9opkZcXPpBjhOuttZFra1WpivQLvRHnFC1rJbv+lLpXXdQaV2frPa2UETslkdoXxSkfwwynIJDBA4B8xgvxZSc0HgbeXicGHnG0i2UQgKeDwSDG' .
    'fPwDxiCAQZCnZZ4LNCdxXobGwXyAoIMnEAY0XnEep+ULn+mdUFZwmnYasZaSdmpdXd0SXWqxdpoWHXAf1tDpdpoa1vZp8NAdHxZqmvYSMV3d9lAa8GlWn53d' .
    'dl0x6pIWGpYVd9CAhoYVjo5srF9kZJcXLGTkjt+ObLHA92Fh2UxGhoCVlQZQd5Zs5I5frA4X5ExhxkDZ4Xex5F+XDmSs7A4+XoCGEzPX/JrN9IperAHOzooB' .
    'rM3emnRRs43N6VPv0deTfF6zBoA+dKya3opNzoHv6VGz082NUYFezk2sivSaUxLviE9b++KZC9PE+BcKoKBEipeL+BlTb9vTzwiSYnv7z2IS2wjvU9OXmfjE' .
    'CyAK4gh7W5LPU++KeKCLl0TTGbh+c45g8HDu6ni8K44ZnWrqK52ZeA5qvHPwuGCOfu5w8GDufnAO87i8GWqOq/hqHW6OcPD+4DhzHY7q+JkrPGpEl+A8MQSj' .
    'RbFSKQtKUkdDQwtH0lJKMSlgBESxPJdFo9PRy2lqzBPKKVIxSotSQ0fFPCMEFzHE4EdKw1JSCykxtC68isgwQUY0ni+4KarQPoyyEZ6wlSUfVhupdPKSX8/B' .
    'SMausAo8NC8qtCk4nr7QX3JPm5J0qdbQqT4eKrgvtDlWgCmfgko+LO7MPBIHsf//PDEHbpKszIACOZ8pVr5KRBFUamhRvJJMhyySPO5/sb6pygJWHzkAMZJ/' .
    'boe8zCwQxDflCof0+7eIJr0UMr3iYj09soiUt6Y3h5AKZcT79PSKe0QH5beQxFA/MgCcUAB75XQHxIqQt72U4ggyvaY3hHDsCuamtLn6nKoxX14psdOMvWmI' .
    'PfKYSvYEW73Ni4uD0VyEoc5mFCreet+xHDGpC70L9k3bhMopX7Ec3rGqehBHiMzqr4QNIP4X0z9Vcol5iPkfCLtM2vcv30K76BxyM3p5+pL+gAQX1aA/U34J' .
    '8iu8YqWNhqQD8j8JflXTlyAI9hBYQRC55O0urcCvpzgPj8C4p64vbS0TGCcG81KOdTnBZHYQ2JAIrSftr8AujzgO83WYUgYnE7gvj66nQC3tqfXlrSBJvIHJ' .
    'gOuTgNKuhoaTrtKAgMnrZcmpoK31Aby8oIF1ya3lKevSyYCTgIaugS08yfWgqeWugIaA0pPryRdfpWQ2jhFUajm/VfCU39ZQHF+Hl3DEbSUOF7ZkX9QRETZU' .
    'X45kJZcSYY/ZnDh29tTkEQ5fNhcl9ln2OOGcEg/RWN1MTgv0FXa1XaRXrQEvrok95ED3X7hdC1HOzNgVdHTOlViLTF1RKfSf+OlNWaiVTHSLWE5R3ah42U30' .
    '6akfuMpAOTAFOsdVP7xHGM/bnp7HW08/mFW8QIU4MLlKR7o6MMdKBbnAOIWF5SAHeN5eRzk6hUqwuEDeIF74BQeF5Qadv9VQ7tM3DMd3R0UwgjpKZiPC0tIZ' .
    'mj9uhtBVnbfT09A3He7VP4bHE12ZKRjGQrfVU26dUIa/QhlGmJMpR93rRpINAYBY/x6DFD+JE5U4VZ4roL3ki2TUviRGz145fFgB/0aADZLrgFOJv5mqSIw5' .
    'T/y+XsYkVMQ2YjMXpozaIL2PyvyvtjsFTLSDDaE2CigaXfBXTceE781t2KulMsO2/Du9r8oPoHW1D8xgo2tJrNSFTShKBreL3zZkc8nml2Wja71cpAeK0joU' .
    'aBl10Kq9BSIFiQzhKn/A754qgs8cwPw8OXlNvKjBlrRTp+0GZM5sOBQ72P3yiozayOJbNe3NdZhoIMFM0YT6eD8hJq1SUbcS+ixuvu/60axvvhJuN6zY1S/E' .
    '4m0nfwShEu04pnp1EcFN2Eyg6C96fjfurNKR4uhfLViCDEzTDeId3qXuBplQ3/YKOPnL9tnKC3kfuNDQC/hZH/nKtkytzGgC2F8iKExC4p8MWO3LNrkQ+Erf' .
    '2T1d3G3rg7HS7X2rknHcA92eChRpZWmJXmlepV4JVKkKil5pHlRJJanSrTHdQ2vcvZ3Sw32ccestHmmJSmklVJ5c7fDxddukrLHctezkcFvtVIG3krOX1e/S' .
    'lPOvlbdXgQ3wtfY1WRte7PFkbdv1sJytbJvc8OT1ca+SVYGXs/fUaLYyYdG8dhkhaFGZtvJ8Nhs9C+5bhmsyLttbsitLBj19cgYbi+sbLhmhdvZ8kTJodtk8' .
    'qLJ2EWEyrit9xhsLWzzwjk3arH9aTXxamv/OLLA4UmsPcw+0Xk84sx50aw9SC2xnkJdCxXmajT/wbNpOfHDabPyOf5oNXg80Ug9za7hIeLi5ZRiIMzmIpTNI' .
    'eFi4iiDF+ouk0mB6ysugEoWk4FzfPlBfXAb0szlIeJhlOIi4cxhIOIileeC6kqDkC0XKG9ju5PvQm1Bk27vQ2+4Q2MH5T3vMHGN1e0FMNePP3HnMI3r9cf1w' .
    'fNDkG9jQ+26bmNBQ2+7b+yQ/o0Ncpax3Cct/I08iKNpJfChNF8Fl22Qhm4gGo15zLwYhY2+ziB6bW68eoUgzowZXPMFkG81laGRXW+glAU38r0Yzmx6jCGHV' .
    'yztgK56k3gClkMC4WLsgY9wI6Tdi5XBp4/dw5QhiHNwwYuNI5TdpAMC4YLuQGKWgQDul2LgQgDBpZRzi90jj2gsfyDHC9dYrf0rdqy5qjd3eiHOKlrWSs12K' .
    'kvWI1p6FyLW1qlRF+oZI7YvilI9hS4aioU/tlMiSs/WeVsqInTKvEwOPONrFwzLPBZqTOC9T/gFjEMAgyONTEMjgAUA+PgjA08FgEGMFAxqvOI/T8u+F+LIT' .
    'Gg8DCONgPkDQwROLbokutVg7TW4LNU17iZiuDw1r+zR46I67z/ROKCs4Tc0OuA9r6HQ7jW67rhh1SQsujVhLSTu1rk57KA34NKvPtgsWMnLHb0dyNnLHL1aH' .
    'C0tDwMpKA6g7CsuKO2hAQ8OjWOD7sLBsJgfyr0sHMlZ2S0dHNtYvMrJYpjBjoOzwuzpnxQDWZm9NQDpWTW/FJuef60k+r1kDQH4fL0DDiZlr6KjZxub0qffN' .
    'QC/nJlZFemfNZnpFL9YAqPf0qNnp5sYpUCLFy0X8jIXpy0x84gUQqf1nMYlthPfxKYl3xKetfb237elnBEmxDEU80MVLounQzIVpYvwLBXdxhL0tyeepXvWV' .
    'zkw8BzUO3gw1x1V8tVx4MHc/OId5d1y/OUcweDi4OXhcMEc/d7UOR3X8zBUeNXU83hXHjE45N0c4eH9wnJShhSNpKaWYoxSpGKVFqaHl6ejlNDXmCSKiS3Ce' .
    'GILRUTAColiey6KYI6VhKamFlKFYqZQFJamj8GKeEYKLGGIPRtkIT9jKkugXFdoUHE9fmmAkY1dYBR4jWhdeRWSYIGerjVQ6ecmvWuhUHw8V3BcfGs8X3BRV' .
    'aOsvuadNSbpU5n+emAM3SVZYpkMWSR73v0miCCo1tChenxwrwJRPQSUlQIGczxQrX5YYyT+3Q15mfxZ3Zh6Jg9gA31RlAauPHFOxnh5ZRMpbAGKoHxkATihI' .
    'esU9ooPyW30I4ptyhUP6+ptDSIUy4n2bXkpxBJle0/FbRJNeCple271yugNiRcjMacbeNMQeeVQVb73vWI6YisFoLsJQZzNcQjh2BXNT2kUle4Kt3ubFvZSv' .
    'WA7vWFVYfU7VmC+vlOWF3gX7pm1C7TzE/A+EXSb5i2rQnym/BIIZvTx9SX9ABogjRGb1V8K5+5dvoV10DhD5nwS/qulLRBD/i+mfKrmBFV6x0kZD0pZHYNxT' .
    '15e2nNaT9ldgl0eEnGAyOwhsSHIEewisIIhcugmME4N5Kcd23JdH11Oglod2l1bg11OcCYf5Okwpg5N1w0lXaUDA5Nd16WTASUBDFF7QwLrk1vLA1PryVpAk' .
    '3t6y5FTQ1voAZFdAQ0DpyfXDZMD1SUBpV/LAFp7ketDUNiiOr8NLOOJ7ibDHbE4cO8sIG6ovR7KSqouvUjIbxwiIEocLW7Iv6gf7LHuccE6Ja7Wc3yp4ym8S' .
    'avIIhy+bi1zXxB5yoPsv1BT6T/z0piwoOudKrEWmroporG4mpwX6uq6FKGdm7AoPVLzsJvr01Be72i7Sq9aA7komukUsp6hez+Otpx/MKq/CwnKQAzxvHB2Y' .
    'Y6WCXGBjXGWgHJgCnV2gQhyYXKUjcm8QL/yCg8LPqh/eI4znbaCjHJ1CJVhcTSWzEWFp6Qyh44muzBQMY8Np6JsO9+ofG4PO32oo9+npHzdD6KrO226hDCPM' .
    'yZSjHYbju6MiGEHf2+opt04ow7IqzxXQXvJFRsCpxN9MVSR1rIB/I8AGyf91I8mGAECsPmpfEqNnrxxtYhuxmQtTRhyPQYqfxIlKqpwnfl8vYxJCFI0u+Kum' .
    'Y6S62gdmsNG1UFv+nd5X5QcdkN5HZf5X2+H35jbs1VKZy8VvG7K5ZPOFAibawYZQG1tW6sImFCWDld4CkYJEhnCyYEvaqdN2A1Rgfp6cvCZexbLRtV4u0gOO' .
    'P+B3TxXBZ3ZFRm1k8a2aVWkdCrSMOmh5ZzYcih3sfveoWwl9FjffvT+CUIl2HFMTVuzqF2LxtujmOkw0kGCmG/1o1jdfCbfIFz2/G3dW6SlCfbyfEJNW9LqI' .
    '4CZsJlDlTKhvewWc/BGmVmY0AewvW+gF/KyPfGUmcfSvFixBBmj7bOWFvA9c7GWbXAh8pe+D6QbxDu9Sd3YUJiHxTwasL08FirSytERe6daY7qE17lRFrzQP' .
    'qqSS6Z4u7rb1wViFNK9SrwSqVE+PtESltBIq7va+Vck47oGWTunhPs649XeqwFvJ2cvqTvZ4srbtelivBvha+5qsDVaudvj4um1SQGnK+dfK26vqV8mqwMvZ' .
    'e/ZY7lp2crituFa2TW548vqZjZ4F9y3DNbSMUDt7vkgZlz45g43F9Q0MNFuZsGheux6X7S3ZlSWDLRnXlT7jjYWbELSoTFt5PjC7bB5UWbuILxyptYe5B1o+' .
    'zcYfeDZtJ7wFtjPIS6HiLR54xyZt1j+pJ5xZD7q1B1yvBxqph7k12CY+Lc1/ZxYGOG02fsc/zTBFkGL9RVJpxNkcJDzMMhx6rm8fqC8uAxkkPNzcMgzEcD3l' .
    'ZVCJQlJlcF1JUPKFItwcxNIZJDwsPNw5DCQcxNK64PynPWaOsU1o8g1s6H23PuYRvf64fjioDWx38n3oTby9IKaa8WfuhJ/RIa5S1rtssu1d6G13CBJMaKht' .
    '9+19l5BNRINRr7m0K55gso3mMoOtV49QpJlRpOW/kScRFO1Ng5Cxt1lEj7BXo5lNj1GEMj6Upovgsm1+sqst9JKAJrgxboT0G7FyUgBgXLBdSIw0bhixcaTy' .
    'm+/q5R2wFU9SjrTxe7hyBDFxmLQyDvF7pBCAUkhgXKxdQFCgnVJsXAjJbm/EOUXLWjBDpPZFccrH/ULk2lpVqiJr7YUP5Bjhes/ZLkXJekRrTsnZek8rZcTG' .
    'lT+l7lUXteQlQ9HQp3ZK5Cn/gDEIYBD5ggGNV5zHaTEfBODpYDCIYpnXiYFHHO2f8SkIZPAAIAmEcTAfIOjgl2GZ5wLNSZyB90J82QmNh8eHhrV9Gjx0hUa3' .
    'XVeMuqSdZgfchzV0uqZFt0SXWqydpt1neieUFZxnpz2UBnya1Ve3hZqmvURMV5dGrKWknVqdpSFgZaUB1LsD+delAxkrk1Es8H1YWDYj2wULGbnjt2GFZcUd' .
    'NKChXSxTmDFQdvgFORu54xerw9mloyMb6xcZoM/1JJ/XrAG9ZqCXcxOrInt01Gxjc/rUJp2zYgBrs7c1v48XoOHEzGPUe3rU7HRzcyAdq6a3YpOAs2YzvaIX' .
    'a/vU/rOYxDbCdIYiHujiJdHY3tv29DOCpMYUKJHi5SJ+vviUxDvi09bUuzjC3pbk84jC9GUmPvECAmjmwjQx/oU8LjyYux+cw49ah6M6fuYKO9wcPC6Yo58a' .
    'r/pKZyaeg5w7rt+cIxg8zpybIxy8PzhaB2+GmuMqvqeaOh7vimNGhPJ09HKaGvNKzJHSsJTUQtEoGAFRLM9lTMrQwpG0lFJoEdElOE8MwTF4Mc8IwUUM0FGK' .
    'VIzSotTRUKxUyoKS1A9NMJKxK6wCCy10qo+HCu7Xs9VGKp285MkHo2yEJ2xlkBGtC68iMkyq9Zfc06YkXS/0iwptCo6ntA+N5wtuiiqvJFEElRpaFDNLjOSf' .
    '2yEvrxKgQM5nipUr8z9PzIGbJJJPjhVgyqegDoBvqrKA1UdfLNMhiySP++w/izszj8RBLSS94h7RQfnpTS+lOIJMrz79zSGkQhnxralYT48sIuX9PgTxTbnC' .
    'IeTtXjndAbEiFAAx1I8MACev+C2iSS+FTBnFYDQXYaizql7KVyyHd6ziopI9wVZv8zzmNGNvGmKPbS4hHLuCuSmh8kLvgn3TNkyqirfedyxHSqw+p2rMl1cg' .
    'wYxenr6kPyWI/E+CX9X0h9z9y7fQLjqTdh5i/gfCLmEDxBEis/or6cAKr1hpoyGC/EU16M+UX1wiiP/F9E+VJEJOMJkdBDZLO+7Lo+spUGPdBMaJwbyUW8sj' .
    'MO6p60suOYI9BFYQRMmEw3wdppTBI07rSfsrsMvOQ7tLK/DrKXkKL2hgXXJrerIroCGg9OQAb1lyKmhrffK64aSrNCBgb2BqfXkrSBJqeWALT3I9aKHrunQy' .
    '4CSgq2Ey4PokoLTJZYQN1ZcjWcSDfZY9TjindUSJw4Ut2RdxGxTH1+ElHATVxVcpmY1jRQk1eYTDl82dvUTYYzYnjre1Ws5vFTzlVxSdcyXWIlPqBypedhN9' .
    'egVd10KUMzN2F65rYg850P19RTRWN5PTAlR3JRPdIpZTFmoK/Sd+elPAi11tF+lVazCODsyxUkEuYbk3iBd+wUGRLlAhDkyu0hWv5/HW0w9mzjGuMlAOTIEu' .
    '0FGOTqESLLdXYWE5yAGetmfVD+8RxvOP4TT0TYd79VG3UIYR5mTK7fSPmyF0VeeGppLZiLC0dPSNQedvNZT74e9t9ZRbJ5Sx0PFEV2YKhqAOw/HdURGM5DpW' .
    'wL8RYIOjNrGN2MyFKQ4ftS+J0bNXIlmV5wpoL/nW/7qRZEMAIAlVzhO/r5cxEiPgVOJvpioljscgxU/iRAOoLf9O76vy+eXitw3ZXLLM8HtzG/ZqqTEhikYX' .
    '/FXT7Q5I76My/6vBLSt1YROKklpSXe0DM9jojUIBE+1gQ6gvKjA/T05eE027IqM2svhWM8cf8LuniuC4Sm+BSEEiQ4Fi2ehaLxfpv7wzGw7FDnYBWbAl7dRp' .
    'u7SqtA4FWkYd2wkrdvULsXh05Iue3407q9uNfjTrm6+E73vUrYQ+i5tTdHMdJhpIMCh6XURwEzYTqd4fQahEO46rFKE+3k+ISbIt9AJ+1ke+d/ayTS4EvtIu' .
    'tH228kLeB/5yJtS3vQJOA5M4+lcLliBWOwqTkPgnA5cIUyszmgD2u8F0g3iHd6lJqqJXmgdVUpWnR1qiUloJqkKaV6lXAlWil6cCRVpZWqx0Txd32/pgekun' .
    '9HAfZ9x3r3RrTPfQGkB3e9+qZBz3hlcDfK19TdY99atkVeDl7FWgNOX8a+Xt9TtV4K3k7GUpK1c7fHzdNn1cK9smNzx5LCd7PFnbdj1Weyx3LTs53IZLn5zB' .
    'xuL6wpaM60qf8cZBj8v2luzKkprMRs+C+5bhXQaarUxYNK9EmF02D6qsXQxaRqidPV+kn00IWlSmrTxx3gLbGeSlUBqu1wON1MPcg9QTzqwH3dqtF47U2sPc' .
    'A58WD7xjkzbrZgOcNhu/458Tn2bjDzybtgtsE5+W5r8zAT3Xtw/UF5eRMriuJCj5Qim4nvIyqEQhNJgiSLH+IqniDBIebm4ZBmke7hwGEg5iDuJsDhIeZhkW' .
    'bg5i6QwSHhwf84hef1w/XcLP6BBXKet33l4QU834M1hdcP7THjPHJtQGtjv5PvQ+CSY01Lb79tsmNPkGNvS+BDbZ9i70tjuowdarRyjSzELYq9HMpscox6ZB' .
    'yNjbLKLcS8gmosGo13bS8t/IkwiKEz/Z1RZ6SUAZ2hVPMNlGczYZH0rTRXDZTRo3jNg4UvnSOExaGYf4PRhH2vg9XDmCOdwYN0L6jVipd/XyDtiKJwQgKNBO' .
    'KTYuRikAMC7YLiQuCEApJDAu1pF+IXJtrSpVYqfkbL2nlTK152yXomQ9oq1ktzfinKJlvbX2wgdyjHAl8pKhaOhTO2OYIVL7ojjlWuPKn1L3qovEmA8C8HQw' .
    'GPAEwjiYDxB0kM/4FAQyeAAI8pR/wBgEMHaxzOvEwCOOw8B7Ib7shMa0fMGAxivO487LsMxzgeYk3U6zA+7DGjrqs9MeSgM+zU7T7jO9E8oKuuNDw9o+DR5O' .
    '06Jbokst1q2rSyPWUtJO0kKj264rRl2mq9tCTdNeIpvJKBb4Piws/C6WKcwYKDvQsMKy4g4a0OrO0hCwstIA25HtgoWM3PGM7NLRkY31i5Xdgfzr0oGM4YKc' .
    'jdzxi9XqPTpqtrE5fbkx6j09ana65prfxwvQcGIA0Od6ks9r1luTzlkxgLXZNcBZs5le0YuRXjPQy7mJVck5kI5V01uxUmzvbXv6GUF56l0cYW9L8mtffEri' .
    'HfFp4X1q/1lMYhs/YwqUSPFyEUIBNHNhmhj/aDpDEQ908ZIBRGH6MhOfeM8dbg4eF8zRHGfOzREO3h8ezh3Xb84RDGEeFx7M3Q/OQY1XfaUzE8+jU00dj3fF' .
    'MYVHrcNRHT9zX62DN0PNcRWyaBSMgCiW54YYvJhnhOAiYLSI6BKcJ4Z5Qnk6ejlNjSkmZWjhSFpK6mgoViplQUkhJeZIaVhKamroKEUqRmlR8uvZaiOVTl4u' .
    '1fpL7mlTkibIiNaFVxEZgYcmGMnYFVay5INRNsITthXah8bzBTdF94UWOtXHQwXTF/pFhTYFx8pXCVAg5zPFIwfAN1VZwOpQySfHCjDlU4pXkiiCSg0tkpX5' .
    'nyfmwE0g9p/FnZlH4peZJUbyz+2Q/S+W6ZBFksd4n/7mEFKhjBHydq+c7oBYkH4fgvimXOH8FpJecY/ooPLWVKynRxaRplf8FtGkl0LX9KaXUhxBphMKgBjq' .
    'RwaAeXFRyZ5gq7ebUHmhd8G+aZQ2lxCOXcHc2YxiMJqLMNRHHnOasTcNsSslVp9TNebLVlUv5SuWwzsjJlXFW+87lp1D7v7lW2gXkHRghVestNGVsAHiCJFZ' .
    '/R+QYEYvT1/Sl0k7DzH/A2FKLhHE/2L6p/oSRP4nwa9qL0H+ohr0Z8rKsW4C48RgXuBkwmG+DlPKIpccwR4CKwgbEiEnmMwOAqWt5REY99T1FOeh3aUV+PWo' .
    'pR335dH1FOURp/Wk/RXYPoC3LDkVtLU0tTywhSe5Hok3MLW+vBUktTyFFzSwLrkwed1w0lUaENrVMBlwfRJQcj3ZFdAQUHrQ0HVdOhlwEos6osThwpbs5qKE' .
    'mjzC4csxguriq5TMxqzkMsKG6suRjrgNiuPr8BLy21ot57cKnlPiwT7LHiecx85eIuwxmxO7gq5rIcqZGSmqu5KJbhHLgb4iGqubyWmpK4rOuRJrkf4L1zWx' .
    'hxzoNeDFrraL9Ko99QMVL7uJPikLNYX+Ez+96UgXqBAHJlcWF+goR6dQCUDnGFcZKAemFxhHB+ZYqSCzitfzeOvpB3nbs+qH9wjjoLDcG8QLv+DP26uwsBzk' .
    'APN2+sfNELqqyvD3tnrKrRN9+sag87cayvrHcBr6psO9OkNTyWxEWFpGUIfh+O6oCOWoWyjDCHMyw1joeKIrMwUrh4/al8To2ZiEKueJ39fLEOt/3UiyIQBB' .
    'ch0r4N8IsHyRrMpzBbSXohLHY5DiJ3GUUZvYRmzmwhWJEXAq8TdTVGb4vbkNe7XJ4JaVurAJRdV2B6T3UZn/+QHUln+n91XpmBBFowv+qtRGoYCJdrAh2fxy' .
    '8duGbC50Lamu9oEZbPCZ4w/43VNFu1/emQ2HYgf0QLFsdK2Xi4kXFZifJyevIVylt0CkIJEOWlVahwIto6umXZFRG1l83YAs2JJ26rTC7UY/mvXNVwkUvS4i' .
    'uAmbmCm6uQ4TDSS87YQVu/qFWM33PepWQp/FpFWKUB/vJ8RVOvJFz+/GncdU748gVKIdAxfaPlt5Ie8Bqx2FSUj8k5CBSRz9qwVLX9kWegE/6yMnfzkT6tte' .
    'AdTdYLpBvMO76Tt72SYXAl/7S4SplRlNACpVIc2r1CuBbr2lU3q4jzMwVrqni7ttfakkVdErzYMqLdHLU4EirSx7oLu9b1UyjoTK0yMtUSmtjbtXujWme2j2' .
    'KlCacv618rw+rpVtkxuem5SVqx0+vm5rw6sBvta+JrL6nSrwVnL2bqs9lruWnRz2nvpVsirwch6Wkz2erG27yaDHZXtLdmUuIswumwdV1tcuA81WJiyafcOl' .
    'T85gY3FwTWajZ8F9y57PJgQtKtNWY2FLxnWlz3hSBi0j1M6eL+1B6gln1oNuT7MBTpuN3/H1T4sH3rFJm6g4b4HtDPJSgdYLR2rtYe6ZBbaJT0vz324N1+uB' .
    'Ruph24lPs/EHnk2QFFxPeRlUorE0D3cOAwkHA3EGCQ83twzLgJ7r2wfqi1QaTBGkWH+RDws3B7F0BgmhSBlcVxKUfAwHcTYHCQ+zmTtvL4ipZvx7nwQTGmrb' .
    'fXoTagPbnXwfH46PeUSvP65jrC44/2mPmR0Cm2x7F3rb9S7hZ3SIq5TfbROafAMbetFj0yBk7G0WoImf7GoLvSRFO2n5b+RJBGbUYOvVIxRpa+4lZBPRYNRs' .
    'm4wPpekiuBQh7NVoZtNjuQztiieYbKNBjCNt/B6uHBcCEBRopxQbk9S7enkHbMX8Jo0bRmwcqawcbowbIf1GaxcEoBQSGBceaRwmrYxD/BKjFAAYF2wX0dpz' .
    'tktRsh6dEnnJUDT0qbjeWnvhAzlGqki/ELm2VpWyVrLbG3FO0UWtceVPqXvVGbFTcrbe00ryMcwQqX1RnADIZ3wKAhk842HgvRBfdkJHu1jmdWLgEQxizAcB' .
    'eDoYGAR5yj9gDAIS52VY5rlAczp4AmEczAcIcVq+YEDjFecFp2n3md4JZafW1aURaylpa6dp0S3RpRadbqfZAfdhDQ/d8aFhbZ8GEdPVbaGmaS9m9dlpD6UB' .
    'ny5podFt1xWjaGhYYVlxBw1FRnbp6MjG+vjtyHbBQkbuls1kFAt8HxYAdWdpCFhZaepwQc5G7vjFHX4XyxRmDJTGyu5A/nXpQDFzze/jBWg4xRrgrNlMr+js' .
    'rUnnrBjA2j71Hh0129icawDocz3J5zXY5BxIx6rprd3cGPWeHjU7qkivGejl3MS0tS8+JfGO+H+hAJq5ME2MiJ8xBUqkeLkgKbb3tj39jI3wPrX/LCaxvACi' .
    'MH2ZiU/5PPUujrC3JUk0naGIB7p4Bg/njus35wiY0ammjse74uegxqu+0pmJ6OcONwePC+bnMI8LD+buB4qv1sGboea4D44z5+YIB++5wqPW4aiOn0MwWkR0' .
    'Cc4TJHU0FCuVsqClFJMytHAkLXNZNApGQBTLxjyhPB29nKYoNXSUIhWjtBFDDF7MM0JwtZASc6Q0LCUME2RE68KriKIK7UPj+YKbW1nywSgb4Qkv+fVstZFK' .
    'J6vAQxOMZOwK4+kL/aJCm4JJl2r9Jfe0KYL7Qgud6uOhKajkk2MFmPJxEPvP4s7MIybJyvzPE3PgYuWrBCiQ85kWxStJFEGlhuP+F8t0yCLJ9ZED4JuqLGDI' .
    'y8wSI/nndnBIvw9BfFOuIdMrfoto0ktIeWsq1tMji0a8T39zCKlQUH4LSa+4R3TACQVADPUjA6wIebtXTndA02t600spjiBuSptLCMeuYOWVEqvPqRrz2COP' .
    'Oc3Ym4bbvLioZE+w1epsRjEYzUUYyxGTquKt9x20Tai80Ltg3x2rqpfyFcvh/krYAHGEyKxTJZcI4n8x/bDLpJ2HmP+Bi84hd//yLbTpD0gwo5enL+WXIH9R' .
    'DfozaEg6sMIrVto1fQki/5PgVwSRS45gD4EVeorz0O7SCvz60tbyCIx76i/lWDeBcWIwgQ2JkBNMZgfs8ojTetL+CmVwMuEwX4cpCtTSjvvy6HqSxBuYWl/e' .
    'CijtapgMuD4JCJi8bjjpKg1aH8BblpwK2txansILGliXCWjoui6dDDgPmloe2MKTXD25nuwKaAgo4xhBdfFVSmZP+W2tlvNbBQlH3AbF8XV49kUdUeJwYUtI' .
    'VnIZYUP15YljZy8R9pjNZXNRQk0e4fDOKfFgn2WPE7RAXxGN1c3k1RrwYlfbRXp0/4XrmthDDoxdQde1EOXMyNQVRedcibXelIWaQv+Jn+UU1V3JRLeIn576' .
    'gYqX3URToHOMqwyUA/G87Vn1w3uEg1nF63m89fSrdKQLVIgDk5ALjKMDc6xUgOftVVhYDnIEiwt0lKNTqHBQWO4N4oVf5T59Y9D5Ww0EI6jDcHx3VC2doalk' .
    'NiIs1Xk7/eNmCF1e/WM4DX3T4YJhLHQ80ZWZCWX4e1s95daZctQtlGGEOQCI9b9uJNkQOFGJ4zFI8ZNLvkhW5bkC2uyVw0ftS2L02CC5jhXwbwSpisQIOJX4' .
    'm2VMQpXzxO/rYcqoTWwjNnP/arsD0vuozBBqo1DARDvY1XRMiKLRBX9aKjP83tyGvar8AGrLv9P7NrqWVFf7wAyiZHDLSl3YhJdsfrn4bUM2RXqgWDa61stR' .
    'B60qrUOBlsgQrtJbIFKQIvjM8Qf87qnXxIsKzM+Tk9puQBZsSTt1g90v78yGQ7G+VdOuyKiNLBLMFN1ch4kGYtIqRaiP9xPi5vsedSuhzyvhdqMfzfrmLN52' .
    'wopd/UKOY6r3RxAq0c0Eil4XEdyEziod+aLnd+MlyMAkjv7Vgl3qbjDdIN7hgJO/nAn1ba/3gQttn628kJGvbAu9gJ/1gP0lwtTKjCbJgNWOwiQk/q/0nb1s' .
    'kwuBPhgr3dPF3bbHPdDd3rcqGZaW6OWpQJFWQJWqkOZV6pWVVJKq6JXmQbTG3SvdGtM9Gbfe0ik93MdWQuXpkZaolLdNysrVDh9fDrfVHstdy057Wf1OFXgr' .
    'OXl7FShNOf9ak7Xh1QBfa19dD8vJHk/Wtk9eH9fKtskNOXtP/SpZFXjNa5eBZisTFivPZxOCFpVpZbgms9Gz4L6yZNDjsr0lu7i+4dInZ7CxFymDlhFqZ89r' .
    'FxFml82DKryxsCXjutJnzfqnxQPv2KTvzALbxKel+fdA64UjtfYwt/Yg9YQz60EpVJy3wHYGeabtxKfZ+APP+KfZAKfNxu8wt4br9UAj9YaBOIOEh5tbhIeF' .
    'm4NYOoNIKg2mCFKsv1FICq6nvAwqxWVAz/XtA/VZhoM4m4OEh4NYmoc7h4GEvlCkDK4rCUoPvQm1ge1Ovu0OgU22vQu9zDFWF5z/tMf+zJ23F8RUM9cPx8c8' .
    'otcfve+2CU2+gQ2+vU+CCQ217cp6l/AzOsRVgqKdtPw38iRctk3Gh9J0Eeo19xKyiWgwi+ixaRAy9jY0M2qw9eoRitFchnbFE0y2EtDET3a1hV4xihD2ajSz' .
    '6eJJ6l29vAO2i7ULAlAKCYwjVg43xo2Qfo4gxpE2fg9XVH6Txg0jNo4LiVEKAIwLto0LAQgKtFOKfo80DpNWxiEjXG+tvfCBHOqi1rjyp9S9aFkr2e2NOKeP' .
    'aO0526UoWUpVpF+IXFurTvkYZojUvijUTom8ZCga+qWM2Ck5W+9piKNdLPM6MfA5ifMyLPNcoAEMgjzlHzAGHgDkMz4FgQwMBjHmgwA8HfM4LV8woPGKofEw' .
    '8F6ILzsEHTyBMA7mA4u107ToluhSl4jp6rZQ07SDh+740LC2T7KC07T7TO+Ehk630+yA+7BRl7TQ6LbrirRT6+rSiLWUT7P67LSH0oB3/HZku2AhI2J1uCBn' .
    'I3f8NIC6szQErKwGNDSssKy4gwvLZjKKBb4PIGNldyD/unT9IiO7dHRkY8oOv4tlCjMGbfbWpHNWDGBWbHIOpGPV9Jo1APS5nuTznJi55vfxAjROn3qPjppt' .
    'bGJVpNcM9HJu9GINcNZspledbm6Mek+PmlzEz5gCJVK8J14AUZi+zMTYRnif2n8Wk3za2hefknhHRpAU23vbnn68JJrOUMQDXca/UADNXJgmknyeehdH2NvE' .
    'c1DjVV/pzFzFV+vgzVBzg3OYx4UHc/cEg4dzx/Wbc3P0c4ebg8cFz1zhUetwVMdxzOhUU8fjXfcHx5lzc4SDllKKSRlaOJJalBo6SpGKUVNjnlCejl5OiSEY' .
    'LSK6BOfluSwaBSMgipJaSIk5UhqWUJI6GoqVSlm4iCEGL+YZIYStLPlglI3wwfH0hX5RoU2FVeChCUYydkSGCTKideFVk5f8erbaSKVQwX2hhU718U1Rhfah' .
    '8XzBlKRLtf6Se9pwk2Rl/ueJOeRx/4tlOmSRQ4vilSSKoFL5FFTyybECTEyx8lUCFMj5O+RlZomR/HOROIj9Z3Fn5rD6yAHwTVUWRaS8NRXr6ZEB4IQCIIb6' .
    'kToov4WkV9wjVzik34cgvikoI96nvzmEVJDpNb3ppRRHpZDpFb9FNOkgVoS83SunO0PskcecZuxNjuWISVXx1vsMdTajGIzmIjA3pc0lhGNX6m1eXFSyJ9jw' .
    'jlXVS/mK5fnySonV51SNb9omVF7oXbBA2GXSzkPM/5nyS5C/qAb9l/QHJJjRy9NWfyVsgDhCZNpF55C7f/kWq5q+BJH/SfD+qZJLBPG/mG00JB1Y4RUrdX1p' .
    'a3kExj0FdnnEaT1pf4PAhkTICSazCoLIJUewh8CYl3Ksm8A4MT0FamnHfXl0fj3FeWh3aQWUMjiZcJivwwYETF43nHSVnAQ0dF2XTgZLbi1P4QUNrAVJ4g1M' .
    'rS9vba0P4C1LTgWUnlxPdgU0BASUdjVMBlyfrgdNLQ9s4Um8hCNug+L4OubEsbOXCHvMciQruYywofqzcYyguvgqJSX7oo4ocbiwCeeUeLDPsseCp/y2Vsv5' .
    'rfiyuSihJo9wB7r/wnVN7CFPb8pCTaH/xFpk6oqic67Eclqgr4jG6mZmxq6g61qIcqJPT/1AxctuvWoNeLGr7SLEcorqrmSiW/rBrOL1PN56OcDz9iosLAcq' .
    'yAXG0YE5VoEp0DnGVQbKyVU60gUqxIEvOCgs9wbxwsJ43vas+uE9VILFBTrK0SmWls7QVDIbEUzBMBY6nujKcK/+MZyGvumGcp++Mej8ra7qvJ3+cTOEnEw5' .
    '6hbKMMIqghHUYTi+O+uEMvy9rZ5y7SVfJKvyXAHNVEViBJxK/AJskFzHCvg3CADE+l83kmx69srho/YlMbkwZdQmthGbSZyoxPEYpPj1Miahynni979qOiZE' .
    '0eiCBhtdS6qrfWB9VX4AteXf6eZ/td0B6X1UXi2VGX5vbsObSza/XPy2IWwItVEoYKIdQlEyuGWlLmxIZAhX6S0QKTptNyALtqSdyWviRQXm58nlIj1QLBtd' .
    '61QRfOb4A373Ft+qaVdk1EbLqINWldahQNjB7pd3ZsOhZ3HzfY+6ldBoxzHV+yMIlSEWbzthxa5+Awlmim6uw0TzlXC70Y9mfXFnlY580fO7CTFplSLUx/vC' .
    'ZgJFr4sIblfAyV/OhPq2E8D+EmFqZUb6yFe2hV7Az8ESZGASR/9qyPvAhbbPVl7AV/rOXrbJhfAudTeYbhDv/2TAakdhEhIrS0v08lSgSB5a4+6Vbo3poEoq' .
    'SVX0SvNbH4yV7unibkqgSlVI8yr1Siuh8vRIS1SM4x7obu9bleOMW2/plB7unL2sfqcKvJXbroflZI8na6/J2vBqgK+1r9smZeVqh4+tvL0KlKacf7ycvad+' .
    'lawKJ4fbao/lrmWGJ6+Pa2Xb5N8yXJPZ6Flw54uUQcsItbNYXN9w6ZMz2IvmtctAs5UJXVky6HHZ3pIz3ljYknFd6bSV57MJQYvKlbWLCLPL5kGYe6D1wpFa' .
    'e2fTduLTbPyBvBQqzltgO4PSZv3T4oF3bKBbe5B6wpn1ephbw/V6oJH8d2aBbeLT0nf802yA02bjXySVBlMEKdbDLMNBnM1BwvriMqDn+vaBLcNAnEHCw82V' .
    'KCQF11NeBiVfKFIG15UEQcLDws1BLJ3CQSzNw53DQGPmGKsLzn/aht5324Qm38CP64fjYx7R69+H3oTawHYnGX/mztsLYqoqZb1L+Bkd4t52h8Am296Fdt/e' .
    'J8GEhtoY9Zp7CdlENNtoLkO74gkmRZoZNdh69QgSQdFOWv4beZtF9Ng0CBl79BhFCHs1mtkILtsm40Npui8JaOInu9pCvxErhxvjRkjbhcQoBQDGBUcqv0nj' .
    'hhEbW/Ek9a5e3gErRxDjSBu/hxC/RxqHSSvjxsXaBQEohQTFxoUABAXaKVO0rJXs9kacFKd8DDNEal9VpSrSL0SurY4RrrfWXvhArEe09pztUpS0UkbslJyt' .
    '9151UWtc+VPqfWqnRF4yFA2DAAZBnvIPGMV5nJYvGNB4DgaDGPNBAJ54xNEulnmdGAYPAPIZn4JAAYIOnkAYB/PQnMR5GZZ5Lp3QeBh4L8SXp8FDd3xoWNvF' .
    'qEtaaHTbdVhDp9tpdsB9qcXaaVp0S3RCWcFp2n2md8CnWX122kNp2kvEdHVbqGlK2ql1dWnEWlYaQN1ZGgJWOpCxsjuQf12HhWUzGcUC35E7fjuyXbCQQQMa' .
    'GlZYVtwDZYffxTKFGX6xOlyQs5E7sX6RkV06OrJ5zRoA+lxP8jexKtJrBno5NqdPvUdHzTawNntr0jkrBhpOzFzz+3gBzU43N0a9p0d6KzY5B9Kxait6sQY4' .
    'azbTSWwjvE/tP4suXhJNZyjigT8jSIrtvW1PXi7iZ0yBEikjPm3ti09JvG1JPk+9iyPs4hMvgChMX2YT418ogGYuTPvBOczjwoO542eu8Kh1OKqCOfq5w83B' .
    '42biOajxqq90OYLBw7nj+s3B+4PjzLk5wjmu4qt18GaorjhmdKqp4/GnqTFPKE9HL0tJLaTEHCkNxfJcFo2CERBJSynFpAwtHPPEEIwWEV2CEFzEEIMX84wo' .
    'LUoNHaVIxSwoSR0NxUqlu8Iq8NAEIxl4qOC+0EKn+tLJS349W22keMJWlnwwykYqIsMEGdG68G1K0qVaf8k9puB4+kK/qNDgpqhC+9B4vqmhRfFKEkVQuR3y' .
    'MrPESP58plj5KgEK5By4SbIy//PEpnwKKvnkWAELWH3kAPimKkjyuP/FMh2y80gcxP6zuDMRHZTfQtIr7iPI9Jre9FKKKpQR79PfHELIIlLemor19JQrHNLv' .
    'QxDfHRArQt7uldPIAHBCARBD/fRSyPSK3yKaEYY6m1EMRnNyeMeq6qV8xWz1Ni8uKtkTpiH2yGNOM/YrmJvS5hLCsdg3bRMqL/QufcdyxKSqeOvGfHmlxOpz' .
    'qulL+gMSzOjl+FVNX4LI/yQL7aJzyN2/fH8g7DJp5yHmMqu/EjZAHCGVNhqSDqzwiv5M+SXIX1SDTP9UySWC+F/ZQWBDIuQEk7qeArW04748GMxLOdZNYJye' .
    'ur60tTwC42AFQeSSI9hDYUoZnEw4zNe/Ars84rSetAK/nuI8tLu01iW3lqfwggYCSk+uJ7sCGoK21gfwliWnSgMCJq8bTrq3giTxBqbWlyTXg6aWB7bwA04C' .
    'GrquSydPAkq7GiYDrn05kpVcRthQ44RzSjzYZ9nYkn1RR5Q4XB1ewhG3QXF8ktk4RlBdfJU4fNlclFCTR2Zz4tjZS4Q9VsFTflur5fxiLTJ1RdE5VzfRp6d+' .
    'oOJlOTNjV9B1LUSQA91/4bom9jM5LdBXRGN1LWI5RXVXMtHipzdloabQf5FetQa82NV2KxXkAuPowBzhFxwUlnuDeMDkKh3pAhXiPf1gVvF6Hm/lwBToHOMq' .
    'AxQqweICHeXogxzgeXsVFpYeYTxve1b98HS4V/8YTkPfYU6mHHULZRhCV3XeTv+4GQhLS2doKpmNVkO5T98YdP65dUIZ/t5WT2WmYBgLHU90HRXBCOowHN8b' .
    'ATZIrmMF/M1cmDJqE9uIGD175fBR+5KA9pIvklV5rjYEAGL9rxtJ+3oZk1DlPPH+ZqoiMQJOJfwkTlTieAxS9L4qP4Da8u+QzSWbXy5+22GvlsoMvze3wV81' .
    'HROiaHQq87/a7oD0PjahKBncslIXMIONriXV1T4ONoTaKBQw0eTkNfGiAvPzI4tv1bQrMmp7qgg+c/wBvxQkMoSr9BaI9XKRHiiWja5Q7GD3yzuz4U6dthuQ' .
    'BVvSoGXUQatK61C6/YBcveyFE8/uxZ1SOvVH9Ued7lLFOs86z+5HUp3F9TTadTQY7vvwcaZ7GMbE9HQM0zXdNkyzMdPdPTE5080wbXK6me7unpxm2NTn+T7n' .
    'XL9z/3XH/9d9zvs1x/g30jCetYG1IZLR8G/8XPwcY4Nh5F/Wv6wNc4aMkfGJCX3Sf9djh2OHpRP+9q0nricmDP+V7ovtix1O/Jsgvb6n/aSlOfiLNwF7SOnN' .
    'Uadzp3Mp+03IEcERAbvzTWlIp4rQCmpj4vQ5SUiXKsmJTb9Nv2oISdcJifdxCZfQJfnz4k80D0+lcNN5JYmFP1zVtdS1CEt+IL7iveKVbPkgTFx3wos/33RX' .
    'JFIkMs/bhH93Ykz54e9HYhYzFrO/lB8/EBuvPtbmfXC3t7m3yfv4gfbd6t3q480HvNp72nubqw8e896xaxol69yOI48jJ2vqGN2y37JrIuskG40bjSOz62gm' .
    '39IXWv+Ie0m+Qr7yozDO+iX9S/rClbgf1uTW5Cv0cYU/XoaZlNo/JzIfWi9fJkSo95GmW1byNcJuHv1F6XmOSho/t38ZHrh/H4UchRx4uR9+v3+/f4m8Hxge' .
    'FR6FvL9/GXi/Vlj1TT3S9qqDuaJwb7S/q7+rkHmvYrRjtIO5a6+won/x6asUS1zK8/YZzNB5/JD6kPrQmXlM/Hb89pn6+VDMkDpDScKsLdUc1RxCwyzJrbqt' .
    'OsOcLEJJ1VNslikc9qcnGbsyK6/K5QnlCVd2X8mUZ5Rn7BK+WpGRl5EnzHi1u1K+evo5yKv5jueOJ+jU63PzavPqKY9X0Oe7z3c8q16nQc354pQRXRZuyG7I' .
    'EeJdlBb5pfVMORbPX0y/mM6pt2B6Xhq6H4hYjYvK/CBbgqP4dyG9m+EKPfFOMXkxOb0h8cqO26e7oVJjsoCEgITSO+Mhsk8V1poVJOcEBV7xIQ1P/dXRy9II' .
    '4pKRyEnISeLSkgmQypDK0kiS4wjICchJypLT4pD+vHxvhmZSNzrlXpTkN/Qn4k9Ekrtf0dCUrTV+jpIgNZWL+g63vmVQYFAgt7r+jqWLpYt6oD73TtBOUKCL' .
    'vjq3JfIBVdSlgga/Bn/UwSWVAnJTmPlLBSeWIpail2EK5k5NJq3mp+UEY9tj26et5eYEJgQmrdvlp+Zj5mPbJuWtpwRPPcMuGiLQ+tH6LzwbwiKeRjz17G+4' .
    'CEMLQ+t/2uB5EZHftypAwjpbPlsu0EeyyprPmt9XTiKwOrs6W55P0ifAyrY47UIouBS4FOiySDgtyCbIthhI6DK9NL0UyEa46CL4/mwAMX6zUqhSCPEsfmDz' .
    '/eb7M6F4xIFKhIryj/T9FatPhzxXFTuQHyM/Xh1S9Ox4qsCIQhXAjNCC0ELFGIDCrHCEFWTl5N4q3SptheUU5H7kfoQl7WQV1BrUKn3khGXlnk4QfJPEOfh3' .
    '8O8NQVIwZzpnOsHfpJvgweDBv+lJBDecdvTaaHlCTr+dfqPR52kL2QnZ0f/OQ9N20nb6bZdHjyZ08Gpi6OvWJ7pPdEOvvk5sHbTvW/QNU1KSUpL27Q9bULav' .
    'PaHYf7HZ9L9Jsv/kBcXm2ubak+oX+xRNCAjVa4E35lSKVJ1COqdB+UH5QlQ6naeKp4pU+TpCnUGdQfmKOlRCp+GFa0GCnyI2IjaCCgXXPoV/Ci/cEAxai6j/' .
    '2/hvrJf6G/excBaFuuyd7F3WMYWwOrc69/EdRZawrLDsHTfFcZZ6zg/nvgyrd4/LHWacfOxc5V3lnRx8ZuzK7cod5H2cZly5GX4SjLzWy9XLJWAY+fma+zU3' .
    'Q+4IwU+9n3q53CMMBK8nRW2uE9DiFOIUrkUTbNAm0SZFFRKubeJs4hQmE0Sv0b60tF4hoW85bzlftSC1on9B/9LijHTVutW65fwFqeUK/W3duUgwbVa07l3Z' .
    'AnHDyZ+TPwt3xGUNug26d3+IF8pOTHDoryOJqsOqw65xIumJTIhMcMIir+mr6avDTCJxronSbM71g5oLnhc817cJOm9Oa06zeR6kf15wXvA8LchGvzlldp/M' .
    '+nggZiCGbNZ6/zjlOGU2xppsf2B/ICbFepbsOAelXSVT6VDrwWhK/NlCgXmBefzoWcrCg4UHo+Zn8SkFLP+6Yn202E7ZTmP/+XRpsWix/Dv1ie1i62I7ZfH5' .
    'F6uVxhBBEuIqISMhQ8IQEuGa5prGIBNCEiERISGTFsJA4tqQyHG9/17PTM/sOnGf433D+4ZEs/1rDj0OPbOG/cTr9yXV/t7M6Gd9Z33e1cz+6CXoJdV9zN7+' .
    'Z/lbrQTNaZ9+hbldmKn31KLVopm5qV/0hPWEuaGpm13UXtSiham7mfXgRm0FbPvPbM9sB0Rtb/nj+uNGbW8HbM3QGj0NiQmb3NZoL9+2dA5LDEvcbrcsd9Zw' .
    '1mhPtNwuD2vhxZkIk4/5GJFVtLGz/fXg68FG1k7RdsR2RNbBzkbR16KvBxE7WRvbUmSyasVvwmbDZtXIimXfSL2RIpstVpMNkw2blSomU3uDx2A+GD/di96L' .
    'PsgQbz6NN43HgB4/aN5r3ouOF88wOG0yQkHMQmmjb6NPPMJCQWlCaTKiz0JMYSPhFSvHN+aCMJfmOmDNX59RnzGQZu3KP0dJqHKfM2scl7PzWkSnXwBb+Qe7' .
    'icTMss601lVC+E1NoCQxVamYc8NP3s3zo5LetdSshPS0q45tPOU+L7w3GAZCVy1sc/liaONHYVw6HhyMnbJt6S8+SE8XsgWNxq1IPTF+YhwXtDIqxUZK7LR8' .
    'rmhBZ5+37FBaTiC+yFb/m3nAyt9+zaPoj1vUpZbNKnOyxOhhfE7sRbSwYEUBurk51r3C9wDl+72Mu+dGWDvOFwg8ZkcbPzbfeWVwvtoXbqKSdyGe/bHJnem+' .
    '/vrdLJVLoyLRvvC7r2vPPdWrNtXefd305Nr4sXuJ5HhRRaIi0kTiprA3RdWkWD92WEeJSavIp7fxhjhYvp689qgJa/KTnhbfLxJqxTwTmz9nxKJn6JM1jQdU' .
    'jYp6WjQk6yGKfAp8JJobtCF6K7PoF5mn2ksnLeU9B3NOQzPoOifpy6uX1fRiFIYPfxoVk4WLdxEK2C9dnqFn6CzNCh26P9nV1Ro1IicQM2ivozfJi/PDMp76' .
    'U5q87oWcqeNfEDdrjG584ffRI30dTfd7sp+J8TT6n4K4Kz+TaKwp47z2WSnT48uC/y3T2QOZPz8rHdyTlHJGcP2kCetNNd+e2buP5qhU4SScN2ngm771lU7K' .
    'qhpWwXVwx07I8lQdqXKo1/B5a3YqSyhFaKz13ue0iUWQ4Hv5It71F6/d4Semau+ECLAXylmuy+Ocn//z4ToR/b7Iglt2I0RwXb5I+B2PWZAxqqZzWCOLK7jN' .
    'VRVh7ZJIBkHvlxktM7kYWsnDgm+dDA/0WJ6ayZJvMBJ+K879KYpmFyj3vljAfYhqg0b3A4sUQuC3gSgZrsZltJL2nHwxRkIyemVnhWyvtt7n39Ve1Pu3Myi7' .
    'f1MkbXFNWPUMC1BBF3HOeeKh2MKg3OKaoyrn8YR+xRND2T9RLEw0TMX9I2bC6opGxEZ+3lA13+Wk93E34dkKPusDfK/clHPf3skDfL7L5AcerAQFy/h1G/mh' .
    '+cNLGt69LwiOTi8nryYf9hzznvkeqFNuByDIUBc5xrvruH9dxdSqvQzksnq85OGRpJ1e4kh2+bwuwAJdq7NKs8NwSDH9aRke6pjg40L0INSWwuJvifWV0qHc' .
    'e0Hecvb69e9sVXBf/cozvOea5MCutzU0VlGwn8RLSKGIXBad5DDcuMvjfl1vq6D0Dtde31FfyfadAnZ9WS4uPXP28GEGIe6Mg3R/odo6f9Wi3zP84mlpHMf+' .
    'dMKHFX78Cyzq60cMOThMw6W5M9IZg/ZF+Lj4uANSDhkl0wyUdIGbv6c5siTSvrRc9yiS083ubzGwByhG/ktt6/kmEbhLP7PDTknHGrBLvzPDSPnlX053m4J4' .
    'mkRa701rjnykhhNerZL17J63UVuq4dOdCnu8GRtVjf3qH8k0bYab3ka11m9mlXft8farrfFUpjSdUmn8dvQr9NsM27afGnn/SEb845uOTlz4DKm9FTWR7qfv' .
    'Q2Pv5xx7KIGxSf3HaqjPev059304UAiNmTMeeaMXI/yJ72dBU4vtPeo+Qu57zRyX9Ij9l5OhwsFP/GvihlG27+vsv44V9Yk77TcaOB4Nl+JfOyk8OjLqZP31' .
    '015hzeiIhL2B42HZ8Po/4hviUrYh/I0GL9On5S8KPBCMh4vaEhLJD57Ecir6KCT9OGxOKEyiNB6uUJR/7pf4JBahvID6hZe7aVuCMUX80VDRcBFVfPy7w2Ys' .
    'wlT29z4HXQgIYwF4R9988FOPvE0xejliA+3GVr67HbD7oB+bdhOm9nD4JJsdohMG2Dl/X40+njieKLNbco4OPCW/GHRuDpTZ2NjffkkVEkl+EdjqdiLVT8ac' .
    'E77/MIBjsPnc31WK4kK6v/nKzf+MnCUngPD3Y/Zw9nDCnN/+T5hx7GIG+NPklFpaeugvhnUWrWMUkvnxVPsX6Ie7L3TaWgaSsRX5VW1ilPuTowUVse1CRyao' .
    '3crC3rb06IxetMzT/02cFMH9s0Jbrcys/OZ6lypxcvkK9y+NMKXSzTPN33XKIpfXK3hP4ydphS8ncJZuEpVvqvfeUCoxqzLv3WjUUijFjzFEcfHtvtmxvJjU' .
    'M2/qHGf4/YIzUSOyY9LqSq9+2zKKN373udYYg1YkLx3376SxT8sjV4+i/CWtLpos9TY7J8tZZM2qDKyaR76OWBPUOpwyy1rq/yht+3BmWzv80HH4q5lhuVVF' .
    'C4ts2wdD2SqL7yzWtcNO+GeZI5kj9jX4I+e2+HVd5X+2FHUtsYS/9b82y6zuUty+wtcrTc9RFx38YIlVvkmoeKlT06Vdutl7JU9QF0aMIOTBXaOHIfzh1YDV' .
    '15wW65StMr3fSWyopDaUqfpztil7emVt8VvzNqmPKQxZUbd0W3fLk2xSErZ0U0v326xtUlkNyRdQSFFJDZLJ2RdsZhcp6WSWU0jTEm8UTmzJohYok5elp58w' .
    '0n6foCk5QRygW5lOkyZdpCRjXKGQSpleLJ94cFb0tI92gPZ8vBiB5vvlDI8cI4M06hfvj+QyDCpp9LqpSCUtE+pIgvypaViJeq8Q21JLxul1J9QR9YpT2hiE' .
    '+BOxUpF007TTsARTk5AEKegNCYssxQ0KfKs4MgPD0+gNX1oUUhrgp3IEVH2NKPAltCCXKDKkNzTEt9AvkaSg5wjID/+a5lflWxURmFmQyoF8KE8zLz6L+I2C' .
    'VlgtlfVNjYMOf7mze+QbseSnauzfKD4LuGl/d6928IgUcCrVdq4WTs5ie61FRUtOy5qmlqMpNhM92lROGWgVmql6YUq/w6mlt/yG+WgW11OJ/1+EYaAy73Bj' .
    'JIqO2wcsHe/q+7Et3Hd2C0w/1tdcf7ky21XNrxubag+5jHLkxTQx9phutaSj1zwUVfUktPFfvao1Trsnl6K8c1xJJ9L8Zu2vTOApRljjr+Vou4KWJsZDfSyi' .
    'T+98yJE+OY00ltygV+NTYowqUpdJk5XN9pel8ufHnbyJVYGFV+EKMy/Pdtsx+P4VuF2OenckuPbWtCog2NatFZc8K0f8c2C4xJT32k/fb2qPXfP7uWSYT+x+' .
    'd+jocOyg+0awaliET8DornR/bPYiXt/0oCF/2GhsxKFLp1z5+YEv3bSOPtO8vkbYF3JbUlud+UijIFZqpdnfVX677IzrjnONx+xKSVE144N6f/usdcL0g6jY' .
    '5w/Y1yXrVj2fRbHOW4cZ6TzydpC7dUZcTRxPvHV2l8D2c1ocpHU2czDSozXtcHL1WyyyfPYAX3Wz/bj6l02WlY6IlxHtlFePicPPq1ayHyajXF8X4gx+PBnH' .
    'Q912+ERlXvlu5b/PEuxqgQkZKoaB1P7T/91//qhJO/ZVBcmIMKZl8evClwSVezZ/9cnad5+O8d3NEAmU/XUSLrqPh49fSUcH/yPi0gj4LSIw2NO5LhIh2M+n' .
    'YRAwwCck0LW+9uoiOKWbSrmrZ92AO0xQ6D8i5bVYzeD+R/cLIoj+i2+UJoY3r7rbb3bbbFUrRAt3j+Q4zdvKdtsqbMv564+O5dL5ZzBfvP7YU74rV9FqK7Yr' .
    'cpT9wi5aIoz8+4OI1Pt0pXSlyOJY3Bty79AI84zSh4hY1qX+yRQOoW04NAlF22tceFHMQmTdu66PEa0/p30utL8l/y6ZHoWZdkMnuI7CrOGr4btPjylI/efP' .
    'Qpgo9ZZNfArP+mf2938WxsNsN9kuUnk89+l5EHXv6SzjecaZgo/uqEYrJJfXHjxYVn35uG2272b0hkL1h+zc3HJ4Gk0qn9NrT9kKdKmDGDNjzM1KuXRX2XOK' .
    'Vbn63kVVz9ds4WmJ3JOLc6rnLSSqfTQPyf7kFEfpOuxsGbxzKBvAHNRC8eLicHimPb+A1/P9rcXc6BJmPrV2QL3oY/F946wKWY9krAePgwsG1Dfer/v4Djhw' .
    'NYQxca1xrTV6fBRg6lBucw+7ShpQkvuc5PmvV6lNSUzDzJXT9Wa9kYkrTKDdYb2HmHogl/DsaYfDeniDgIAs/zPCbpcyrUItEt4+eieVxrRQvlyeuljx4F99' .
    'tv9lS71sv183L5cK1iZxYf+ZJ8PfFCsYXxjEV+eqwq/dS0T/DdWG8vgmnIGLjWvb6p7sC2oFek5Sut5Xd8do/fKktHp07Jwk7a9N7tGi2xHE/zEj2iS7R2PH' .
    'lrxp+4hqI3r5+wmH511qoPfp8Lvhd+G3njHnPqWTVSL86m+GO0W060TUSyfnqgwMXmT/FLEMv81w6nC8ez0sMsddaVBw5nNn6fkx/SdxE+FT1SIlQ0VDhraX' .
    'pFnkJc6vTqgLH4xJ+p8ON+eSYCN2fr9qeaTk/5qhnFxcnrIJeezGgUY7KwcH4YZMOxb75kivupZTNnQnYqdVjadOZhf7J9NHvwaj+obINg4HHfSfo0zq9X4Y' .
    'PyI3W8Xr+UJ29F7XR456MFXiye7qbYrWVXziK/BVexVec153rpVj6OnPi9ic+WnpYD3GVq6T9YLJYKSTnX74VsdW7l4rwEWt8XnBQczH5pX0bcRA3oJ7LV3H' .
    'ilbFplaHSQlcRdxWCa8fK5WP2/68Ta2hVZIybzyPoSdva/xD3RxHpGqO1Tpe6fuyVZFDybwx/qKSEBFBHEu0/stl/TOV0GIk20LzwlDmspforY/oz1dWEQec' .
    'nKbwrlc6COk5zkeQFvBdpspCMVUKTeqfdTtNcUye4pKFR5Sn4fmQc/8h+yAye2WWZJnEQzL74e6Sl95E8jcrV/MPaea3G8LC9Mwm3KzrwjXS1IKKIUsNDJ94' .
    'm6WZf1nTcF1dkiVNvfhgI1KUe/x63pXTg/Pwm0bRKl/UyZziC/tjPW0Vt1WhtYiTq7l9LzF/NRWew8l8Iw/OojU9lSv+Ma8vY3xFPAZ73/zKp4+LbWKwVFFU' .
    'y5ft1lNL9LhmovsKjSRl0gpX27VfcfHPqOWMakukkboKrb7mf4CpLpnG3zOXZfS1ZFrVLvsQ00Pw57QM/2jTQNM838s+Xr/bTA+K/vzKsiLyIofh2vvMFI+W' .
    'so7LMvIf83yj0n1egq1l5Cn9rqWnQn6CP+TneroZTtLlmcp9wu3DZf6xfi1ie1cTS7XKKL80QcCRsiprXdMWq8o6/2GagF4X4WCzf8pWeomgbSKJw6KY7SSS' .
    'QTXFg9TU+a1jvXmdaZ3FO2f3yseaiVYWtWX/VTW9z7druH+VmGj1L6fNsPZ9tUWVu4M5iell1fvEJtsio7rHptUe5o5vmb8MyZY8CK34UqEQ8b0T7ZlVurvb' .
    'w/daduZexq4kmnbp0e5v7IjfW3s1K2D1FQQ8/aJv5xX92OWDma3uEUtHkwW/sQ37rrkh7i7O7pq5Lbu2rZwsinWR2X1qgrkF7vdLBVl5lFvLMpkk86M1bXZz' .
    'XHObOb3JpxnJj0hFz1AcH6fw2/ztZ8f1zLRstWhFH/Blz7x2l851KMV0iY93x8nL9nSWVs51QM7zTHBvRU9l9rW973eJd1fOLUZ0ybzub3XHZba1j6ywlgzT' .
    'utO/Mw4Qb4h03ebaHqp5Nz4+0/N+vXlinYt3e+lt5cZ4z4lxQK2Sjk/kw2rGMFMkA7TPrpEn4hZV+p8Xi5r7zUIC97jWNzk8cfhYTU/Hr18mCWnbuBgV1RsJ' .
    'TfPscxObLmeEtVgUDH0KXNR5KXrc6old9tRTdDouIf3nZFDzlX3CWI3P6mKAzbXTwypEPvndO6WpGcm/wnvK1YiefwY9nLQ0PiPo9jd4UFnfx77lmhVpi5c5' .
    'yHwcl3DlSFO/HFBSltOMioeWmaTgt2NOP7f5dWVe7Nwz3P9T7Vp5lyITsw5e/zck5DcLFLPXzIit9ipv8MRNtm2nL0sDSP8stYz8uInR+ODAp8j+K4xElD7I' .
    'VuzpGw6vdSz6S/kyElpR9ksM0W8k9Ir0oorstbMYtOM/vBwK4lXunO7UC5o0Kkf4q0x/0Pu+V88IGny739rE+eM9vSO+b71pEKdByeB9dpOR4IwMh906bUVT' .
    'ENay7352nqmTOr2oY71p/fv3z33xq7BXbyyHokR67T5Ho4zO39k0T0bVfSx7fzFsw/FlLKXbp6A4G11KOAbp0Oez2jHpl+6zburTSRRvPWm9s8l1FK7buXDS' .
    'Vtm1FBQ3QQ+cTwha/+F5K0td2vpZev73ArVBHEfr3wtUrc/ifoJiWoL/6hBklL0tVV2HbaXESJN7SX2zusP/e8PzUVGLiAEj5Ir1N92i2kfFaRIzYj+eXjWM' .
    '4qtN1iduGMyLB5sPQx4+CXHrp/t9oMiDaKY5Q9LG06ZIJEG8/eayPmSlWQKVvpG2I+uuMec/pw1tliUlFLJv/zWKdFxn5XQ0tmysNbbRtuXQdlw33mWp/7W6' .
    'QkawNXou/yJulQTp+MypAtNBkNmavaLmwTvXLmoR/uID80ffFk+o2XNcaiWRb/lCNfJTA3vfIlfw2vLldDpUYLJaXjtx23NzFSsIHjh5C//EdAnEQv8wEfSi' .
    'MX7carc0aQzZ/F/chBXjdVB8nboUY2NM3ZTVRIn6hFTBo8arw7jdIJJCtX+v/5UmPdsNGrMzERu+MhSm3qPooHlYKZs67OZNu05pJ+bCYhtuvjCk/JEpupfG' .
    'YYFiX7nmma3ugJKbGM7bW0PaY7FjN+FhyrcmGcyyYUnBV/+yjd9biT3+8Qlz49oYoTTwIxOrHtFBd3NX3lsxJ5bkT8adlFtv2dGNH4WJm49FFAta9mYkuYV1' .
    'NzD7I/cGs2xvb9LwGv7eonp+F7yf30W3jdDLe7dBv2LE/Pz5nVrKfMfcYcgTvaBncSp9LL3dmwz5Xf69/vvbKNu5yAsC68YUb+IjEYmiaJvuQgiMDaYasJPI' .
    '1n/b0ixETywp4CLehHxrISA6UvitlkOwsESxnqX0aLZBN1vXYOpp0pAAMln1v7kSu+Y+CccWQ9sNmn/JHLq3JcjVHTShho62PhvcoYbvfI42JN5tSHDLlRne' .
    'Pa72aD5mSe2q7kou/2clTDZ4dVGyh+KIi3VlvHwpVaNSwnTmNoIyeFGnMni5JmXAazzo6rIchHulwntlPNjlmrF3YYV71v0igjeC6WxfeuTqBcKBlbE89wE6' .
    'Ys+L81hDTpWUZkcEeo+D8gn5jpAsTHFU9B8rV684EQnEj3vDjD+G6xyo+AvncXuweqTc4r73d6TMtou5Weok2+G+b+16T40dc/NgfYE8044buwD5fst3XbRA' .
    'av2efohbaZ1bdCevS7TJbnyhk5w6kyPzRnJ8iSwbdyb9Ws+iv6OJGuPHVIGzwLUexozE3kg66oknmeOPEFmMpnie8w8N1BWyqGeeTqloi+nXEvJMMyNLI3ph' .
    'nnuIM2gICGx/10QXCLL3RmQT7W/Z/sr0XuP8Y397OxFiMRPFuTcRcqKiJZzdzJm992qmV+Uv++F1jzKaALvAX9TDYc/eZ+yttqJ/HPqG1MV2vdBU4+tpmPmz' .
    'o9Zz1OOHvPzQno22DQnhmctOqT8aVW9T6hUy38jhpy7Grc/OyaYprsel/ru8aKX/ajW9Zoi4KCjs/CT+0y4rheNO6uOZ+EiMoh9dJ0WR/RVB51PEUyfERZE/' .
    'wromrNIv9FfTDEoMJvT1v14sSizmTjjnfbk3EVj2Ofbn6JyoVk3z3erIFeg04Vhub7FbNik/vkOQFAiwE1j+JX4s8ic3tlX1/WLHZkf1l1d5voveZVpiLcG1' .
    'LI9tcnyRTOS7TecOvVXX0Z/ZdGu/pPnmi7Gh/TJM1ATFRhrDZuOxSaBvi1ZbSa00uzCxcItrW7BV2fHt3hDD2yck+Y65PbyL115DZovCJNTHe2de2y50aT2N' .
    'ptsXjaiLTY43jY6mDIs1Pdt72G+erAsfMx2bLWJTz94W1bY/TxV+v62g2GzqS1U5nWCOWBHH+LopYlrB1/srncOtgmil6VdNRSIHxVsFo9bc1HYnhrzmS6Z2' .
    'JrKtH975tcvvose3s/uDjxJTWreuFXXG8/s3urMNorV0yvLmG+8Hdcq2Iu495xPnBxN1jhrzfM2ix4P713OWo5fzw8bXu9/VWzSUIx/nr+ccfpw30GhxOGNm' .
    'e/oVM0C41GFjWSJep0Viw6BFJ77y0KHlUOLdVEZKsTA3VSnm007hTma2KkyqrH99JH1vTTeqNXPyBCoWWCgaAk0asgSyamgoiCryUv9Z0ROdlDSQGeQY2ykH' .
    'Or97ZRpY05D1zUMgizcr8FtDg3GDx2/Gmw2Bwnr1Dd74T7/HiW5ozIv/Nvxj3CCK6alhnlLnjenBj/+tuTH9vwcxxahTG4xN/Lsexf8K/tE8u2lw/827wNWJ' .
    'lNfvqP0kKfhcIaS3MxBjgfv9BVdab/Lz2XBp2dlkp5DucNkn4mOZdLE4zhQ/uTqrMOh1LxwuAjEebHEvBO7+01DVcsQ1rpn2ydvwPWS8zM/gfoJrWxHdLbuP' .
    'Z3CkNfl9UDvaxc0M51/zzW+uej7bgjOGNArc3N6guLZd3rkKr3dKWiuDYdpY6+e5L8ZRkczpd7Z9Kv4Nos7RZV89V/89zrEzrKPOK/+pW//q9hWZCuHZyk9N' .
    'ydk/PnZYtXujEk2ai3WYZmNO+0wPyBYC2gge6lu46e+XICcZx/l5fvhviDWv0FSE7gvuTaeAgQjC55Q1V6yyxvAzMhFyd0Pmu4xvoxD8WSHsx0PYJwQY0AAA' .
    'QBaAwAXAgDkAAbEQ/Akg7HdC2B8GGOANACARgMA6wABnAAEkEPx5IezXQdg/BxiQDgCgH4DAc4ABLQACzCD470HYv4OwLwIwYBMAwAkAAWOAAasAAsYh+JND' .
    '2H8JYR8ZYMAKAAB2AAK3AAPoAQSMQvCPgrB/D2F/CGAAMgAAaQACcwAD9gEEdEDwb4ewHwJh/wpgwDkAgC4AAv0AA+oBBKhC8JeHsF8OYT8HYAAhAIA6AAIn' .
    'AAMyAATcQfCfhrBfCmGfB2AAMgCAVQACzQAD8gEEkEPwL4Cwjw5hnxlgQAIAAHoAAm4AAz4BCCCH4D8FYZ8Kwj4JwIBRAABlAASQAAZEAAgIguBfBGG/CcJ+' .
    'IMAAfgAALgAELAEGIAMIGIPgjwZhPwLC/jbAgH4AACYABAgABjwFEDALwX8Jwr4ghP1ygAGBAADyAQiwAgxgAxBQCcG/BcK+AoR9IYABjwEAvAcgsAow4CmA' .
    'gFYI/oMQ9jkh7EsDDPgLAOAIgIA7wIB0AAFOEPxJIey3Q9j/DTCADgCAHQABIYABBwACmiD4B0HYP4WwXw0wIB8AwBoAASqAAYoAAiIg+MtC2FeHsL8BMOAO' .
    'AEA4AIFvAAO4AQSUQ/DXg7D/GsL+Y4ABuQAA5AEIuAIM4AYQEAfBfwvCPjqEfQWAAc4AACYBCKABDPgCIEAXgn81hH0iCPvRAAPCAAD8ASBwAjDABEBAAQT/' .
    'AQj7xxD2nwMMiAEAkAZAoBlgQAqAgAcQ/Nkg7Gv9X9gHGHAKAMAcgEABwAAWAAESEPz1IOy/h7AvAzDADABAGgABV4ABDQACziD410LY74Gw3wcwAA0AQAkA' .
    'gV8AA8IABMxA8A+DsP8Rwv42wIBEAAC4AAS2AQZoAAj4CsE/DML+Gwj7BwADZgEARAAQ2AYYIAUgoBeCvw2EfQQI++gAA/QBAOABEJgGGGACICAOgv9PCPup' .
    'EPYzAAboAACYAyCADTAgEEDAOAR/Ngj7dBD28QAGFAIAEAIg0AkwwBhAwCUEfyMI+0cQ9sUBBlQAAPAHIHAIMOA7gIB3EPxVIOxTQdh/BTBgEwDALAABYYAB' .
    'PwAETELw54OwrwdhHxNgwBkAgGAAAor/BwMABFxC8B+FsE8PYX8JYIA9AIAhAAJGAANmAQT4QfC/hLD/E8L+H4ABcQAA/AEIJAMMyAMQkADBnxDCfhOEfVyA' .
    'Ae4AAM4ACEgDDHAAEFAOwZ8Lwj4RhP1rgAEEAADeARAQBRggCCBgA4L/MoR9Qgj75AADhgAAMAAQQAMYgAAgwBWCfxiE/VUI+20AA5QBALQDEBABGEAPICAF' .
    'gv8khH1fCPvVAAPwAQCcARC4BBigASDgMQT/Qgj7iRD2qQEGaAEAWAUg4AgwIB1AAAcEf30I+/UQ9r0BBogCAMAFIGAPMOA1gAB8CP64EPanIewfAgxYBwBQ' .
    'CECAEGBALoCAAAj+aRD2IyHscwAMoAMAoAhAQAJgACWAgGoI/m0Q9pMh7O8BDMADAFABQMAIYIATgIBACP5HEPaTIOw/AxhgDADAF4BAL8CAPwAC7CH4E0PY' .
    'b4Cw/xNgwC8AAOsABK4BBrADCPgBwb8Iwn4zhH0EgAGxAAAOAAgMAwwwBRDAAcF/AsJ+IIT9LoABqQAAfAAIHAAMIAQQ0A/BPxzCPjOEfRmAARcAACIBCHAA' .
    'DCAHENAPwf8thH16CPtKAANiAAAsAhBoARhgByBAGII/M4R9JQj7tAADJgEAUAEQUAYYkAggIBKCvySE/UkI+28ABjAAAOgEIGAJMGAMQMAHCP4jEPZtIew3' .
    'AwyQBQBwCkDgK8AAFgABpRD89SDs50DY1wUY0AUAIBOAABbAgDoAAVsQ/Ekh7NtA2E8CGJACAGAOgAAqwABrAAGMEPxpIex/h7BPCjCAEgBAFACBAYABiwAC' .
    '1CH4p0HYF4SwjwowQBcAQBoAAT2AAQwAAvAh+FdB2OeAsG8AMMAQAEAaAAFfgAH0AAIiIfjTQtgXg7CPCDDAAQDAGwACFAADqgEE4ELwd4Wwbwxh3wpgwAcA' .
    'AJwABJQBBuACCPCH4C8GYf8Qwn4MwIBvAADQAQhIAQyoARBQCcEfAcI+IoT9BoAB7QAA6gAILAAM8AYQMArBXw7Cvj6EfT+AAbEAAM4BCIQBDOAHEMAOwf8Z' .
    'hP1HEPZtAQb0AQBgBSCgBDBgHkCAEQR/Bwj7XBD2EwEGtAMA8AMgsAgwQARAQAIE/0kI+4gQ9vEABqgAAHgHQOA/gAELAAJ6IPgLQdjvh7B/DDBgHQAAEQAB' .
    'DYABygACdv8v+EPYD4Ow/wZggBwAgBsAAm0AA3oABCBC8LeHsJ8GYV8JYAAXAAByAAKhAANcAQTEQ/C/g7D/AMK+L8AAHgAAfwAILAAMoAMQ8BqC/ySE/T4I' .
    '+zcAA2QBAMwBEDADGKAKIMABgn8whH1fCPu6AAO0AQAMABB4CzAgC0CAEgT/Mwj7AhD21wAG3AAA6AAg0AYwwAFAQCwE/zoI+98g7GsBDAgGAKACQEAKYAA/' .
    'gAB3CP5tEPY5IOxzAQyIBgCACkAAHWCADYCAYQj+BRD2f0LYfwcwQAQAgA8AgUmAAXcAAsYg+OdA2L+BsG8IMMAfAAA5AAFsgAFNAALqIfjjQdj/BGF/B2BA' .
    'JACAXQACPwEG6AEIiIHgjwhhvwLC/jnAADkAALwABEYABhQACFCC4E8IYf8Swj4uwABzAACVAATaAAYoAghwguBPBmGfG8J+IcCAKQAArQAE6AEGPAMQ0AzB' .
    'nwvCvg2E/SSAAdIAAC4BCNADDPgEIEAPgv8XCPt+EPY5AQaoAADgAyBwAjCgCECAJAR/Iwj7mBD2VQEGpAEAKAEgwAUwABNAQBkE/1MI+90Q9psABpADAPAD' .
    'IJAJMEAQQMASBH8LCPseEPbDAQYQAABgAyBQAzDAFkBAFQR/Iwj7byHs1wEMeA8A4DEAgUSAAaYAAuwg+JtB2OeHsF8BMMALAMAzAALpAAO+AAhIheBPCmHf' .
    'BsL+LsAAcwAAtgAEZAEG2AAIiIfg7wJh3xbCfivAAHcAANcABKQBBvQDCBiH4I8GYV8fwv4dwIAeAACuAAS4AAZEAggQguBfBmH/J4T9QIABGQAA+AAI/B8M' .
    'WAQQMAXBXwbCPg2E/RqAAZ8BADwEIIAIMOAeQMA5BP9tCPtLEPZRAQYgAQAwByDQBTAAEUDAOgT/Owj7IxD2HQAGKAIAoAcgIAowgBZAgCkE/3oI+1UQ9tUB' .
    'BtACAOAEINAEMCAbQMAFBH89CPu3EPZ7AQYgAQCwASDgAzCgG0CAJQR/MQj74RD2UQAGCAIA+A+AgBbAAGUAATwQ/Nsg7L+BsM8AMCAEAIAaAIEnAAMOAASQ' .
    'QfA3grB/DGGfHmAALQCA/wAI5AAMyAIQsAjBnxvCvhOEfWuAAb0AAKgBCCADDOgEEBAHwf8fhP0xCPvoAAMmAABYARBQBxhwBSBADIL/MYR9Ewj71AADKAAA' .
    'pAIQUAYYoAQg4CMEf0sI+8wQ9v8BDDAGAPAJgEAXwIBHAAJ6Ifj7Q9hHhrC/CTDgEADAHQCB5wAD+gAErEPw14WwLwBhPxJgABEAAAIAAgoAA5YABFRD8O+C' .
    'sE8GYb8ZYIAEAAAaAAIbAAPuAARcQPCPgLB/BWEfF2DAFQAAFQACvAADMgAEHEDw94Cw7whh/wBgACIAAE4AAuIAA8IBBNhB8M+EsJ8NYZ8MYAA3AABsAALr' .
    'AANEAQSkQ/AfgbA/A2G/A2AANQAAAQACsgAD0AAEsEPwF4Cw3wthfwFgQDYAgFsAApwAA1QABORA8M+GsP8Xwn4fwAB1AADxAARGAQaYAwh4DMHfAML+IoT9' .
    'GoABxAAA4gEInAAM6AIQkAvBvwPC/iKE/XuAAQIAADoBCNgBDBABEPAMgr8whP0yCPssAANsAAB0AxDAABjgCyBgD4L/MYT9Wwj7JAADHAEAeAEQaAQY0AMg' .
    'oAmCPxOE/VoI+9sAAxQBAEwDEHAAGJALICAagv8yhP13EPaDAQYkAgDQASAwCDDAF0CAMAT/Tgj7WRD21wEGHAIAcAAg0AIwIAVAQA0E/ywI+w0Q9qsBBuQA' .
    'AKAAIGAFMMAUQAAjBP9/EPZ/Q9ivBxiwAQCACICAOsCAKQABXBD8LyDsL0DYdwQY8AQAQC8AAVmAARQAAmwh+ONC2J+DsI8LMMANAMAhAIEjgAH1AAL+QfCf' .
    'hbAvAWE/DGAALwAAVAAC6gADyAAEIEPwJ4Ow/w3CvhPAAFwAAAQABIYABqQACHC5Qaz3msdi+LocIZTrvB/1VWh/OTciyvnrcpRQ7r5zhPvCXnllKs6OeznO' .
    'QuXeTqr7wk55JU7qnnt56kLlzh6OVN36uEvSI3yp8Ud1Luv4SfI2WfyxUcdC8vzHNrFZQlHkB4t7v+SXcMj3lg5+LeLIkx/g7P1akl8k35M/+IWzuHTTKbW3' .
    '+daCmvlupQ5Fs/YZc13tHcrKM83wnvySPZtmEVr8jsROIqmjLc7jv+U+k3zRdr3U+6I0A9HUNHb7vQOiQxb/HfuuyvlKTh0EYDqjokgGoE5hHqA4S06hBGCi' .
    'Oh8kN85EzdEQ7yRHETfOzezQJDfuRM0R08wkR9E0zu3MEItKqJAHRETii5JHSgSo4EeISuCTB0RGqIiSR0gE4KtENhGX/1w+bl9p+tlOvFy+ctxEvPJzuf24' .
    'vOnnMfHySnn7Q/FFtxfZN38Qb7sRGXpd2RARXW8Zutl6EW/ZEBlce7tXtqzP9KdfVq+cvdzSt66efn9uyfUxUPDney7B84+WPwMPq5g5uheRUg85kKq6mVMX' .
    'j565IfRUUiIcIVA+63FDqCQo7a8TOLV20C85YqiZUz3UZ1AtqTk6nLNhtiV3Zd6bGqjVZJhcCsUfYAitndTEXxqoxWeYDF3SHGBYqp3E1wyV2yMyxnx9YyZn' .
    'fLOHSWT2Wm7PzBjz5jWRnPHrPUwzoptcDUZz7jsz/U6eXONE2YHGTuMBnsTcRtlOnkbjxAHZ3Im/fQsBJZNOEwuTfwP6nEqqcyuPGH6IfKk+EsllqPzyI+8i' .
    'kTkyeIE6j3nhIjKROjjvgpo5ciE40eYEzdDolRQCCe+gw8ESy+2Oq4tl65fbQapdHhSiDjtRKhS7XSIe0Q5NfTkDL4zHx/gGeBYVAkjTSgSY0kaUoXxK0qEE' .
    'Rph8lJa8Bf2NObgvRI/M0GQ7rIxF0ayOZM2MO0SPjNFkrTrM8J0mET8fDxrgIw46fZ40OMZ3MkD8PHg8iY947PTZYHKQ32WRbH+UbpefjM5lf3F3lN9ll2yf' .
    'bnSRn2zUZX93kY7fIoxgkNa+iZ/A3mIwrImW36KJYNCeNoyfgNZisCnMfpHsrJeLdnZ4sXeWjOtsmHaRbLiXa5b2bLGXloxr+Gy2X+Asfbop+bw/PVlg+uy8' .
    'qV/gPH06uemsP71JYPr8LFnA+xVZBiMGogAZhnfGK0RGAW9EsgwMxlfyTgcXDDSWxjcXUZP88tqFN5PaF/xRhfI3F4WT/NryUTeT8hf8hVHa82NndKLBXcLz' .
    'dF1jomfCwfNjwnSiXcFn83TBY6LCZ12xM+ceolnpU7Ee6TOi51NZsTNTHqLpWeexHlkzolPn6aXHWdOLB/mSpdP5x4tZkgelx5LTi/kHWaXTB8eLkln5H5ui' .
    'OraxF7M+diw2bUdlYX9syurYXsSO+tiB3bSdFbWYRfiyyfF/ozqrKZvQ8eUeZxbhXpNjNufLrCZOQse9l9l8v7d1arPwxpbatPSJ9xC8l/QR2oi1vPeW2rz1' .
    'iRH2tLRu7gKqns/jawXM31Td4T+Xri8+CXBfMJA+WagPKDZw1yR+lNSCpcGtmaRB3PKIG0uTmDupRQPrkWYSFnEL9yMNcc8rhMoPN5TpbSEMBVdXXOkMV20F' .
    'IVxX6W1c/38fIjMcxBC/kzUuw5A1HB80viMzPM4Qn7UTJMOwMxw/HpT1np4n67sh38T7LD767zwThg2pQbeNq4ZyDbeGqY1Bcqv7fSzojjHrQvvo632OLEIx' .
    '+31C6I7rMSz76DF9jkIs68m/P1LNWghGJlMJ/p79GGmR/DuSalbQ4mMylcXv2ciPgpvps6a0n/I4N03z0mlnOT9tpnOa0uZ9mt00/ZROyzmbF332OTekdTo9' .
    'Onf6LORzemv0WXpuyHTr5+jc1rOQ9M/TGWz70lqr5y4Z0udsWvsuqxlsLtJa56v7GdKrbFou++dFAeiSF6SsFkWSrAEX6BakRQEWkhespOhFkqQBFxborKTa' .
    'WhmBZsQSpBnE2oFaEmak2hIZgcRmWqQZZtqBElrEW6KIN+xahwFbN4ei7IgBWluiATfsh1qIWzdaouwBiIc2LQH3bzmON2zuj1veBmxw2LRs3L895giwuedo' .
    'ebsRcDyjJ6HTRKNZMqOjqdckUUIzo1ei06RJIzGjQ6PXVCKh6Zj93wfffOd2xw/O2b7/tec7Zrd/8HXO/8/xQ362b/t/zjhj/kp8wg8CcZQejPH5BwqfPaQX' .
    'TerUuy8KJmuqOc+zoEDffkbSPolC8WwSnWQbpZ0CHeUZyWT7NsWzdnQSlO3J0wG33ZMGCcIVzafPHJO7N27vM+9Z0uoaQxib56pfcmVtBx9lKbKlCWxnpQUr' .
    'HgmwMWzITh2aGoXJ3lQg+DeYzZt2BYrkODkgmoo4dOUEIjqZdiGK5Dg4BZqKOHXlIAY62OXryqptuhzZybrkq+kebdrlH8mquWzq2slu5qsd6brcyLbaq8p1' .
    '1NzYd8iqttbI3cjW2Kt2yLXe2MvJqta0dlw2CxlUujrtqzAU1yXl8t2p1PExJBXf5aow3NUl8eUW7yt8e9ew8nph+C6qIwCtjJe8WmAvbmCTEAGBX9t+gzLw' .
    'tfXAa3+lkTmy0IngfgYhiT+dVndsoexvR6uJ2cT/dfzItCLliV0QT0ogWK0lpXlepoDAzMnssElzz9AvPrkfc1y927Y4j/zk44fDiBDKTEvBei6nUTZ6+8zn' .
    'crblsvIMj/h9yR9k4FMQhyU/TNn68WRQzJRSZlhawsX+7x9WPp123kW89uVBQ86iA9claoMCvVsvm7EoZbHZrgPDJeo8PbfbSRW/z9PW/L1e01NRIqp27Us6' .
    'xwwGzrk3k6J+n23GlHobcb6UNeWGPu30sItDXnZQktsxo1q1ldsIz68vxfpST2e8qkKlumG7Jqf6jspubnvbEqk7xtl7Vd7YTo5qR2Vhm4RBgRFPEWueh89A' .
    '2e7XoXqIR6/fYVot095VK1thlbR6GHrto7KnjlTY+B56YlqXHxtqDjlOZIpeeQvh6lzhq39SufG7upE5M8lhf6jBmWVC4lw91l0rStKRY0aikfX82cOpGtcu' .
    '4kr+XudH492idbXtBDxZWsYcWYRTIm5dtQ8rezAcNx7qm0aerGtjE0Tav/tDgVq763vhu7pujE3gHK79p8ad4sgX7XKFwrdu99IXZQUjfO2hqb7zWc0J5RGq' .
    'r98ywkJrE8ZyQciaHQZnpRA7biIV8867b6WXaxy4nAK1VhjsH+J2iilzLiLGU/A0nlCyolf8esFkK4Cb9iYCg3yKlD1J04NphXLMGu1EnKsVKdRF1+VFUbev' .
    '5Y4faTSb1viSrbly63DYh4i41w6/Kl7LF9jKNiBxRl0g2HN76Ja62PVu15Zyp2zLRKrxrddmRBVKajxYVH1TyJkmySdRnVEWvqalUI7wOnnhxcsHaQpvOEvm' .
    'ZGs/c6bIbJa9UniB9Hrua7F4nqBE3N6LXzT54yg/NERpiGYye0ikMvUS8qlRfgi/miHqkZ0h1s/IjHM5puYN80nPQ32dX0k3LUJA/9nlRcqhR25pncZb1ilc' .
    'pkCxk+tYmgfmdSWvz302jUQ1x8s+VGMzsRbqRJnsGK63PXN/WZ51inFfiqf+doq9mlW8gKkQ3ff834bk7wXFdvdyZsn4v68qTo0dXgjxYxoine96ygUOkxZG' .
    'lQgozxC51Ks7oAnx62LxnceqPbs+E69+K6DtJMaNhHWZnIZr7m10FI7u/tXqINUwavxpkd6qjF8PunamVfqR55eixRltPwaJ3nH3Mj3ZVYaO5H1Mc33fr1FF' .
    'L2e1GT1WeuQV47UpPy52xzyW11tRDvop2joTGmNHOR/jr6inskTRMRMtFkXaYLsiSjkeapHYtiK/mKD96Yl814y5aFQDZczqSMzO95XudNXtpeGizKRepXG5' .
    'tf14TP7+7a6hosSvq8rrcRO7wvLofakm5S/w1ZEUR1J2vvcsJaiuY43tKvHHDJS7pffId0ouf1Up7pVw6VpgoP50GbPDNPS1p7jXQUp54VMi4ykT3XY/A1PQ' .
    '5XoM40i5bEZPh4Lj0qdt6lNq9vjR6szRc8St3MQhpJrL7Myd+FI+n1VUond2Q7+qL1MKUBN80EpXzF4QWZaa+a0SP+C1qc4fOV9HzkjyISle4XuPZrPkgs33' .
    'YQ4VB9tsjhfNZQl3GScj+olCCCL2ygqvG/J79IzHCwmBGMpoy8Ep0YpUmChLKDh8q2b22BlyqwlYwaQP1F+MVqH4+Nfeb/2qQpCr2yAYWkk6/JJceV+zUSWH' .
    'tvZr4ZgkPqM/qiJgtodI47CTZfvB35qKDcWdTs1gkq7JI+aqrPoDg6zYokb9it2E7KziWxEegZa2L+uNuVW7edE6hRNNaKEii1cIt5+5/ncutlkV3XCQp5tV' .
    'yNPwn4hIZMOOJQNPtjDaZz5uAbv8SAZkXqQaprd5MZfM3Ig2+XSRoi9YshHfX1TFsG9dTUzRS12PWEbxZSOLMPJM023O3l1KDsgaSkRHYK/qyIZKJS7qYBjd' .
    'jqm34Zoq/ZRFl03Umw/T18C7rVeZfNt1K/e6zQx7qkN2RSIa64u+jsaH2/oZeayunWaGJ1yswdSMzzfJPzaw09OVJopZb/4JZmTZIm/4xEUXb0cn8qd0O4ju' .
    'IkFs0/r7p50g6idMvM3/+7PQiXy/tAmy1uGous4s32e9tq0s1vt6TPQO/7us3KAca6pdpW75zRGR1MPiUWN5RaKBh99VXxrLWxexVKX+Z3hMpERY/KFfXK69' .
    '6jc5zw/0gV2en2TYVVV9q3ZXDhgPq5l3q9vJqjG5B68w5twqLUlYV+vOHPCxzTnaMX+TV3P+GLjCX3KzqMN8tk/0B8/Lg8Tu3G8Ph5DE226keGEBR5eo8tzv' .
    'GIfwkZ/FCubAAlGRbs0IwfyCAU5x1T7RFZ6XH771iu7wQikBRhXWndj58zykRKHnOBdI9wVxxgT+tYjkmxZC37AubtD4EvxRTavW8R9bs03NlWZwKCtioYie' .
    'f3t+lxTy7LTh0cpZkjinbANCJvuuOKJM/TPOr0dlDyRifrISX4mnyNRzciAcvWl9GTKKkxoqvN6dTxGOKCL+TLwhGZXv+Orqj9F88/QWhzOageX8ENdCCArC' .
    'EO+g6H4YLTEFdjIt2jKrvuOoBRct5QF+RgTW0/0UWmKcx5G0+GI5tow3Cjy0uLv4n9Oe0D2fFgygKXfyE6J5Eew4W+wVgiXqeVYqvSBU/Dx4wpHRT+ws2EsS' .
    's2w55KWgZ/EFzspzF7GAYtpZT7HiYC9MmbPlneW98Jo0vTruvbaWampNlyM3bGJh+1ILbvWWFrqaPbc3ZESDF5kThgjtHQGEV4+RG2u4GjQOGV2yhuW/ajB8' .
    'XXv3OvOBqWNPZn6NOeIAXqZP/N/a4YcpDqXi8exKfPMYE/qDWTFTqI1/Xsijphp+8b4iMdy3k3DG+PZA7aN6GC2JuvR/yyMMc+i5Eo5eIgrc2cldQX2sX5e1' .
    'VayMhP+caEwKnP56uBu5W9H+s+BDZf+Dso+fU7xsmT6ed1Gfc1qyYxbf+CIcGV4GyC9fbeAyLTf++lCS73rg4Ym0UvcLd09weeOD67XVd7OfApmX/6ysA80E' .
    'M60CXa2vGxhWRjxf7OXQLu/YuDsv00sjj/N02xi4d9GrexLcuP/keyE74pVGtxtlQnDjeu1O4IaE5vXymt9tgg9N8MXNX9eXBLJPnkXl/rpRecWpLuihrdvX' .
    '2nZlI5HAFq4Q2rd4XVmFZ1q5Z+n5xO5LjlRFnj1KzI3cokNf45dQ7s0hoXur1WplgVIbv48vFBIGFv5rWn0RS+XE25T1IEPi48NvoeyXDTUo+S4fswIQKZoe' .
    'ltXQ1oZ2C+QfNdDWBofy5n8LZq+9aEDPz0KseeCFmBEdTRiyRmMSpIpmEp31uisH76RJuu6K5eSo9120cRDhN7zuffsroYqrsuAr+xcnN/tlnBXSVyVXN0dq' .
    'yCFPf+XEqY5dLivvioog+zn491caKCJEjnhnLZwY6/gp+octOzggCKQJv7l4WOrWrKu0ljViP3+rJkDyxKamzp+iTd5h0EH8+4Di6aW/WdOgv3Vl+LbrTfiT' .
    'kAwFQZc0f7TwUwrx70JWZzYqwnrpUv2TlqVeQnxJxU3ybJevhWYHKPwdvqP5C9kk9PO8eBdUhZFz6KyJXFc1p9EYoNMtSoBRd+gsRZRT5YmS3DnVSvqqkTS5' .
    '814D5dWcb6Nk8PwjApugfh4at4SqaYxUpTZSEiYcpuStmKoyTi+8IvmDX6yln9mT887wizhFq2rXfv9J57H43tRvPUrLdsnT+vRsqbg6mfszfdFRDGdLHqZJ' .
    'tqucRbiryLf3cm+LOp54onxWPZG9/Tib9Ahf/MmwI7nQFeZ/0oLKEtInaaNoBhmpx7T/nTX4hGJ+c81+b0HyatbwQY8X0exLMusRcRcpobmOcd2KlC/4OV1J' .
    'AZ/RXg9bVJUV/vys25F6E0OqXTHaNN+hfkKW/CVIcjwJLQcnbslZ/NeN45uu9jP9X86zXlI9TsuC13wYUe03+iazfxyllmt7rp9jCKpQNPYI9p/zqaDKL1/z' .
    'XT+P0n8j/uvsxrlLN6frDH2JXQVZf8Fx4wg96jRURunH7cVll9zCmS0NedSnW4ehPpfzWplzh6GL0Nva0xqZSO/zvsuFsi7uJTkalSjhDxfs296OjGYqNbe3' .
    'ttzkXi1hoWTaEzu2KhfNwmbcX+NlduQlxXGN/GU+dIZp4Mo8MCrQaJePGhH+wLtd5u3Y8otHhYD4ty+PlkgUreXEvTx1Nd4XYQc+51ciuMW0M/fVwmGq1Fyq' .
    'fDx4YXgO2d58GFzVX4RV3/KJ/ObB1Yr95XvhnYn3jLEml7KgZlSYt9CU9+am9mGhhRVlYQ3ehXCBqZD5BV9Tkdp+k9pFLZOQ+X7N3g1f4UMvK16XTDzG3ebc' .
    'MpMKgZ985msnl2UNtM9eGrMPBelfqz3b5fxZJlD4y9W4a6yMXMlccFfqukz/2dDDXdvdoCU1QexddvOKf3yBJmuNHolsu0jVn8uJkqQFEaiumvnKsixJDPE5' .
    'qJJQxBuJrnzbsg6UXIOmy5ibn2a6vsE3vmy19uuKTCBpLw8mMhJ8gdL9/vhBglICfYI0R/CQ5LRdZP/e3R31zlaAdDk2iub0ioj4wXwrWnT/3fHe2yGRguPs' .
    '/937YO8ED73nmH4gnfA8G2NLwLxaHcP8Of3bPw0xbUn57NQTbuz9Hs/f81AXxmDgPCtJ+uysw0DddlRH8qqsUBmD5XP1G1Knagz6XYFs9TPMAH3TvyOCkvxV' .
    'SwMqm4Kyqde8Jlm425J0VUsjCn8FPdd6XVJxafMFf/XWqOg+zQ+JunZ5akK2fYYboO++OSC4wzsf+pYJW0CHaaePN5JaoKj8lvqDCS9dCvUO+pALk4A37V62' .
    'HS9jrjDj3tsaO9pci5rbt7QFHHSM2PNyReu8AoOeMdNX3gYfxr0jpj2X3T6ofTL2IXugWDzuFqG5fO394WmAmg+qom6xcaqaiCKqZPHDCGMRSV2ZYkWDmOnb' .
    'K88PiZo7WSnSaqgFKDNZmtE6Mq0JXyKMxb3+FZDOGEcnSMuotrdGaDYZN3xZa1Vs0hRv8G36ouifpflPS20nKzhFE7U8y29usMld7z8vu+Ssv4ppiX0zR5Zq' .
    'CS7/Kdol1695pWmpzZTJTRdfzFjO2CbIRV9oTc/YjhWHupTX+83dRBjr7f6X8pWJokKf1KBwVayiaCm7x/bQ20LXMsWikOpELGOJ52kczpd2YySpsNG8k8Q2' .
    '4TiEapy1p6pIz05SqDL22vQDBAZQTpwl0AZ4OoM9EO3RMDj4DtWwd9cxOTulP/5zRjujEPS2HZNqbiv4b2C7lL2NCD2c3Kyy3k0ScaCbp8IDLVto99WgWZTH' .
    'rtl6rJdKhMAoeaV5uzG5jigrgnGZzuX4qfGXXX19BFIH8S/mS0tPSVXJK3eN28l1/uK7CM2/yQkrmsF/5JFxk6aewRSfKPRvkXxi/HWp3YkofgNTfJPW8mIM' .
    'xxLhK/vDe3W2pdecscf3+ifjcXZsE6JFN/gaFA0zaccqb74vLzWKhP0+pC9SbotDwCVOr+99iiD/32EeTlFx3EShdtlV/GWjjcp1Lvc/ZLQ2k4q1j1bKTqWf' .
    '+/MsxYom084ePY17fvkox/ltVb9KNKo899gfz82mtlJpLDXfk4Pnuqifc/nG8nb8MSMVyBtCCbrqbD71RVrlnej6YeUoPm65Pnbl65B5ynazkR1SkDqiIyoS' .
    'oUxsj0Meu7ivHovRjU0VIv5BKgQlKiVE3UldbRmPQcrs30GPI83QkpMiRjqjLZL9VRWJ0u9LCje52T1isaZRI5MnPJOn1SRucnszFGJNk0YmvE9GTqtnmuRJ' .
    'KPZE3XhrTEb/H0X1FFYJo4UBeGfbtjHZtqfJtu2d7f7cZNu2Mdl2OxuTXWfO1be+d12vZy0S/DUgaDZdnOW8NRgqumCmI4902NmkFAUSJjsRLIx2JLfyrtE5' .
    'XAxSMEcVti2OJrcT8KyJOFMSgYBJG8lrowStHbwLHeujbQRJPAtRC+NDC2JPYYqai5uePpixceIrfhIpZKAeR4RKu19qb8FMYQyRW9Lk9u8I3b8q1Rwkdlbi' .
    'f/uRiu/cGr6X2k8Yf4E+exM/0hcRILEQT9fCymeJGpgkqlnd16GwThHhQ8triBokGWdY3ZHKsdYQTkMhJd0aZmuYWIiY3BpqZiVZiLJ5IHHwKHyDsUMgKbJx' .
    '/Xi6I7qCQIZAJtwQyBxybD8eg4guUFAPkImcBxIPJ8c3GMTU2WMYBIwIYuo07AEBI1pvHMSez8gCdcEVLuNiIF6WTcBh3MMnj2MgFOKudMBf1g87KiOseiYv' .
    'XxSjdeMgwN2OIZbDYSZNIiY61qyqeo7UDaLbYDg2zQWU/7sBmGyD5WrYbm82dChAm8Woc7RtGiY7uu6v71PqXAP+MxUEbP3a4rlUW6jYVNtWtGnI2+jQqFIo' .
    '7UCjSLFvty+jqET9rTjdj/lURp+wgGpfVkXe/luRoR+z9Gk6YYFCoRStoyrFvnQBa4r+KbH/aRGLfqo0oV9pzuxtul2mwm2A8Xe8TJi16baihQ+xtazMAGN8' .
    'inuYdWILlGbZSfFtijWjrHt86ICPjKIJiaX1dtktVOKJRkkLkzouQou43AVKd29xJGBj1xqePhjkKzTXfIHHJA4vr556sNah+fLDRlwNtwWBSf5iZ47ByjdY' .
    'GP58yZfkNW32KqHzCZ1lp6odlaoX004gPXplK36qP9gPmXjByBW6kqJTKdldkshhyQYzulcA1T6dcgA5biV42ndrGjkueLXfd6sUAh+U1kV+vHOC31WaRgE+' .
    'x7kim9vmfJ56gl/WtUMB3sq5kic753zeCY6fBiqjOM69WJlvk3XikDlfaZvPc+ZAp0qV3vVwXpBaSAVi7DlRZsab1koftnHuLqRiAKWdKA/jTaVqs9o4PahS' .
    '96TQnRekOUwyj+ra4us4TQ6zpFvjD3mrgKwnya5A18qTI9ZkXnAOPgylYpcXVtfKoxNgMm8xB99PdHCXl2PeKlbgUbLr2oWixFJ/0jH6C18JuJILB1GZc1K9' .
    '8vNF8rmzMlHDU5mXjG8kwlFTQcO5M+Gv5KeyI1lf+CivxoJfZc71SYTPF/AFfp6HUU2ykQV+h17wTbIn974ivBVUNSI1fuUnvFT3YZVtiuuiuiCeGr/jClGq' .
    'e9GqtnXFMB1Qxb0vj+gJVc06qC1MRFG3ShHUJhq2pltFFDKN1yoKAcTzmBYlaoMIWQAeiRmHi9C0AaeJRPHAQ8I9jozEFkVpREOm2/AIIYDG1IcLEWKiQHGa' .
    'w/AFYxHgdJOdKEm+/dJrOyNgoaY9QH0P6ra5K9qppp1xAeylPeAdytyykaL6CeDPVP2y0NHR4gyl3vU3erfp2fydwqIakpbZB6fcrJIRh9HbnLa8kvk64CeK' .
    '6TWvYgWjN50Z9r8OZjL7JBj4YMbsU4FNW8loqqB0c4PCG4Ci+C9NeQLgFGlnRYtiM2ey6IrgRGMV4F7d+3oSXDhFsujgimZjFaxEtHvsiiflihRpRWfhYjN7' .
    'ONzhEntdX+3ltKyLeyZENFEPyYeAK4nkiUceGoOraHjCte4L4KzLg4lHGh7kq2gQwrWLbrisy0DUw0EKzZXEhaU6PAh3FmG3pToIvEUW4bpxKUR54zFeRF5p' .
    'o1r58XFeWZQqPwKyIzle6VpjxPFxAlkUvypesiPjMSk5pLpxXr8jFF6CKjLZqiMUAl4/MtmVmOrekws+3V7d6vOVE/6YxdBzbTZUFahj3eqVi17+GLTQc3at' .
    'BRWo8+jq475Vfl02yItFVC2VMC3IC7QFNpWwaj6YacZgtvrpeuiQakY2Pshn/Y0a8Ak/pnromuApNj7wJ/3qDahJv2A+GKaparb6Gl89SIiNyedNPz1wyJqJ' .
    'Z6jPIYOd4U1vQ++hP1CgzQ+NJo8qieDqNpDPEOSw4cZHcKOHZKVGTdvw59COIeSmt0Srh2ZIZXVTZatHiIZkddP37IfCWeCRmIL4Z+D32eGMnC9zWNvHEdmp' .
    '2OdXkOLRDFiGnSckNEF+0OzHqcL3kRinh+2J/KIKAmS+PQDGCz996hdzYBkCH2ogGjP8VBm/suCnJpej++tnKRrzFEIgv/LN3J5rCPX+b3hl5tKgaX5Uzwbr' .
    'CBMRlJ8iyocsMcM9VduiaTpcrlMIxmAA1+nG+CcIb4mDY+jxSG6EtC1XnSlRGB+Jk33wscj48s3xXnTFP8eRkhDQB2Pe+5GSMBDHY94tcfljF1sghTHFgq2W' .
    '8504m73c4ETf5/hzhYLmrXFQnO9ebkKw7XP8dnz++VjLjkJCXK6NX8jzXnB8rq9t4tMesNPk6njlyuvN8Ye9jHqOgusCze9xGh4rNccfsvZvOQpSwy49Zc2r' .
    'v+0VmNXfZXMcnOp3/whCgwGIQqBQ9Gwz31PKABnZDWVrTDqBdyGWedZqRmr7Y5IpgBKEZEWPYA5UNivKliBmwdXVN11U/cHTsKSg0lUK0Kdirz27hIUeA1VA' .
    'WxMcF7j1/JZBfJICrUWCwH+ZMcHn/mM4KIICy24zGzyQfBR8jE4fx7m6crsCzqZn2naNgba7f8nYJi25UzFYA7vSeoxU2kjaxeXarl/We3YUO09lnjua2sU7' .
    'ldpe1q++8KvWneLKcvKJsvxro543vvA38zPiyvwqiHxydwKfK4n1gbJoom4Ezro4xM6ymIrRFGcvvclL0DvUcJ0H6aH3OUK5f7b7B3qnhXq3E/4kziQIzeQ0' .
    'Tw/s/BHaqZ+eTsxNUSJOxW78oeCnq2weU7hws2m4G6tS4mLbmbkzsllkZWdHpyd6KISOFve9wW2vinxP2HhNUYj46nHX6l99CYFH/n39HHs4mv3EXC5iqUwq' .
    'MS1S028gQkNpRVpuJDLKLKF/Fclk4hxXYVsQY+/HHHxmdR1pT2YSW+FTGOPnYB90RvuHrH0Mdw/jEJfyFLPhdGhggGys/fQQAxOXEnfvz+lQA9/WJ/Jlj+2t' .
    '3fzn+WcvP6LgFtLHV6ftnsP81Sd8N/+HHxCj8ycKWDOhkYvdKnq/4aijypYLIaoRupEJUI+wH0Q9qy4ocaE/ozYzLKV7xSSMjcFTzq7HVcdOUs4loIVddKfS' .
    'LZi/zlxFqltd2LH9xQZjRHgBthvnEmTiC4N6gbzrm4Uxi00zn+mgEvO5NNNy3qxzsRM3bX43YlyWpLRdum/ONh2LW2Cna8WvjzVQYxdszBY7pl9iR2DPT/Qr' .
    'rNxuEKyUpcUxPMUgr1bZmCsMshW6tF5YPSjF4XetkUZDPCRXMPWi44iknDu8hVdxNYOCuIKpbKUPJWIpgkWFrwS9QlE1UzufIE1sfOyPSIE2+hrBCwe2zXsZ' .
    'eXxxG/R3nn/vvGJQq5xIRcdRf9YKT0WrsrBwsFzfSluHZPeRShJyDjqAcHSmZzDgV1PZ8ftYn6+Dpqoy2sfxfZBSuIHoAcbHr79LLWmBtwbDYQnQWezKRPOP' .
    'yg9HQVZDlAW0tyVGBwNqoZnVDOdORRquHk6Y3dDHBw7H/mbQ2Jeu9R5Ozdh2xwfIRHMvvVtYrNwCqzzbj8Ro9Vhz7R9CRKyrQqtrnD2EaH9rGr4UguNU21Ta' .
    'emO//isSrW1QuuuOVY3Qa4vrVQwuuqVtEABvi0lOTWvNbucPpgBjaEDkTopMbk1q7c6CjaBgDSBkd9nuriGrQaMACTT6+foSugqS99XMF6ItMgb0+AnMavfE' .
    '8OZlU2SoMgn3ZU1FzWrHdjDkZbNnqQr+iM+Y6iiZ90pCTRii6V+lw3JKKkrMn89wIv89hGPgSF4IncoxyhObHBrWaXijHn8QmdksHMsXG/L7sN0wXi0+5Dyy' .
    'RTjn576qzFQyEhPiFcWsarqimPi+uB5tHtI07NUQxc9sRZW8E4gJWSZrQesr9p9I9BmjOSdDcHw/rBVtrsQFZ+kyYHR6ph3ol96Q33qR6P/s6Nir9dhPIG+8' .
    'MX/1MkHabOhM49rN1CPht1/02F7DTqDiduPb9U7v4rYj1Nsin7cT4U41M8BgZCLzsfKRcacgQ3QS9DLgwLND8iWyk6UJYcJ3IuSaI7wB7Ischs0TkftHP23/' .
    '2hoPp81MQ42agyU4DH9O/qDlTyYybgH1/NgkYTWlSof/EVm2rR5aFctQvhGmCVnnvN4lQqVqLmo+L0/WpOwu67ou3yLyy5zMaJ5BXFTdvQMF1af1BqwYaOXi' .
    'HUAy9Orz7eON6zpr7WL6rweMvRJYiXkh49svKWwoyOL6OZiB24vBeStZLRHuKOApwtqYuUBMnJtT6GuIqQ7KUVypQ9uM1b1fhaVUyZZUyEc+5EzeBJPi4PU2' .
    'xXXHMbY1YnTEoYaQ4hB3NMZ1RzG2NaH3xqG+OOeUDkVWEBf5E42lh78WvDjXJGNHVsyU+k/jloe8JipymWjBi894TfC6IJnKKGmIc6nYeCrOwI3xgrvqyylZ' .
    'yHif6k7D0YGYAtbGzhBkdWS9ta42YelmGQLG1rWQZM8NzB4FDVfXG0EmLQbP29ocmmac3z076yrbJuptQiDtB1K1vIGkVPpIcq34hNRE+j/UarNJQQn06WRa' .
    'eeH9SfQpy7xWFmgpQeZBnFZYZqnz1ku8VsYWv4OwwjlxzcwT563rb0yWmbWuMa4P0Emt1HtB7TcLDljK1xRHB+S4cwa9jqckT3fMOysMOwTUtF8Lx9/XJE9f' .
    '5GsrDAsE1MwvO8ffKS0MKi02PVgtLQTN9CY56pktulToZj0tjS1d+GrmOVQBx5ZyMIw4bzjnzyh29EAp32Npy7cfOPD45zAfP2mAFmNmQxQsawAkgD0Ez9hi' .
    'P+W+K1330Q+UXw26/IaZqTrlcS5gAvpzQUaxTsYGgK0gtkAXViS7nSDl/5x+GQltB4FHIOcRcKDV+QaTR2gzXutDnfU1elVN3tzEKPJjQnh7DiJ3LjVmmBqc' .
    'arcf5i6aIHdKbCs9/bYi90cApNum+jWjrFHw4eCISAlIM/LhskivYMxR4HNzy0gRSjPis+BKr7C7Q0oanHxZVFrClxwpfXmo+UOqS9c+Wpw7wB/Vqj97SCA8' .
    'h2LqdQUc+j4c6sY0o+AgPGP+d9gVoOb2oHZB0I0SsYhly93mMNvl7SNrs3hjVmjqUrHx89zNNsDHWrzy3GyBPvVCsKSnlgOX0XNXZ3HrJlmoQkFoQDQrBIrm' .
    'mhUWECgANXb4n+BwqX66XSNGcRDtCij4FF3qR/c8eAqJwLuCrShFBZLbWUeqfRYZ24EO3S14Ebo0cyFkPiJHD/HrtWNSV45iPZpMzJfn6V5FqetK7/OWCvhJ' .
    'FAH7k3eKmRhryCHZHN68cdDBaKK2UFdDdiSc8ZIeptqz+PGsSTKUHkTEz62eS6jkzk8A0YJ75/Csw+jV2oOrYvcqNJFKp/vo7PXwqtZ0uKvA1cPV2v0DdLem' .
    'osOCpHTnbM7j6hr0tJvA1f1pp3w0bOHmXy7ZOaJRyuznp9urcMo4N4fNzr+R8oVW0Q+3lNfQyE9XT7fh9g5xD5SEsqPPOcVcyg/O18X2yE/hbnf1zQl+xoXL' .
    'D1w7xJKmix+rvdZZLunAzWB6Xczf/jfye/Dkz4mRRm2PpuYkY6iJX+COKfS/dTcT3EnQzMfaDoB9jpTCx83folAQfB5k5+D6dheuaArSCKJQfCHgZDYe0nZo' .
    'Ma4K+rb6l662CArSaDZQT+B8ZKIQ0nYIaLYK267IA5IjsHmkNKQDsDRSJHHDMdeaN8/bxkakomWRkiTII3vXQKMb/ZjVGIcbzd3tPSCy6IgkTV4+7J7D7vOq' .
    'PsJNV9acnzds/hUAo+tgH/CV6sLMtWHj+FoASDbtSgV87XvVnpPp3LhwvYq07A004ub4J++nHgQC+NP7RXP2Gr1a0vavwKY9tH9jHvAHagEBKMk6l2UeterA' .
    'dROs6aunNLDNbM9WnqiVQ2T+327nXFjcgAMtFAAwhX9Z59nDjjm5LNna4Q+s+Sb95lkkvYQ5hoNbGHwTHWX95+ZZJayDOYYES1iFH3vxA7wbVFO0H2V9RbK1' .
    'xDW9+SYsS9hnBXyxGztHhj87s0olBov8EYWKMb6+r+hhh7r1lTXLJIW5vjG+iv3A8hmvta+ZSvLaqLbOMzG+vMo2hTGLOTB5PVdaZ0ELa0TsKmHBW77uBx15' .
    'INcLBCdI+uvItYvPW2oyYVAF64rH4xrrKybz6AEeP283PpgbS+pKbHLhDTU4epc7D8Uts7YH8r9neubiqB9QBCil5BIhRbucLCTAJo617KDzyNoIM/1fEQQt' .
    'mYshRS1G7CTA+sIfKBIE1HBhzxTs9UZ5IZyBI89HtZEdZx0jtWdHkYHPnY/2D5aESEkdI2e1z5GBR7GPluhu2Z32ne4P9uiEsSeBI0fPZ5EdtbHuSSf22Xxu' .
    'UUdo7frZzRLNR9sSPIRRibG4r8eJVwe2zUd/ttEI4doP0hMvju2RXmPTLV4vrg7QoszbEyWym/UP0i/QXu1jj2fO9adeDwm9ss+9vKbMZrZ7lSoCkwljIbNt' .
    'Xl+3zZSmYmeSQwMJhei8MdA464t5n2ZspvRfD7O9YmdCMSoIewHW2ZSMS5/eo96EatLVn2fFViReuYN26CbehNJLxZ/W1eh5Yia5dlZeViTEXvt2SWLWhNWU' .
    'o5/eS+gk+2KvdlbEAiTKSjayF6+2JOdeSuMCys/2ymRPKzaLtnleNsrjAkrn9h6qBSvAuWd7MuXFFZsnARKlOS9Z2/Nze1WPuRVggZFruP1cv/6ovqvy6FW/' .
    'UThcR4Eb7tz2nL6rtHJ4/+6VPm/6nNtcVAFcx0OB8px+utG9PfRov/6cfodyOtlc1AOj7hyMFYH7PTNCoBvDtaGQ3/pXJB7DwCVzjBtA6NqQQXQ94xK26tNf' .
    'T3SZuZvc094QgaHXzYE50FNU4KqWXE99cgeKPoMeITrGAA++snISKnnx/R13BiQeYwCfEVYpTx+41uSHQtrj838XnwHhThpUQkXTI2SAFofSfZSS3zEmXOes' .
    'iizELCasxJQpku/RNfCt69iUsyzkBk9dKTDmlDV+EJw1ouMr6osV3+j5/8CQm3MVKzq28t92/FGspygG2TH2N8f9EMusI+f3X/dQmccLkRGOKRQis47fOWPu' .
    'oU7xFxxEUgqP/Y+2IyJEU/EckB1/x367HxLF2+Y0iyi4jzSiDanguszYzqClX6i4sIm/DkkpGcos2Mwk2uKKuzSqLIiDbJRkXqVexWdGbGRUDBsTVYZsXZRw' .
    'F4ZsQFIyXkrkVTevnTOpj9hVnY+vM4U3A96hzf+pkWFjVz123swUvha8IaY2q4lCDrxxQKaqFSCSV73ePM6kdhZ4pyKGqg1wzIiyx+QjMlZVD5AyxPynxE6S' .
    'BhCtuvv0qBatIm36TwnBD6fKY8AlL5AEZyDw6c6PYUYUgb0KsTrfL82jKtCFZOC7Pg1422ogusPiPPDM9Z1Ws52vjnZRXbnDInqbxvX9XK2fWKl+UZNfs72c' .
    'T3/BmPhd/4wz0GrgXL1Nn0h6UbPMLqzKZ9Qx960svBvA18G+aEXQL5oLTQ2m3BdgpNrB3klNQBw0AG0lsr3xutC8JBbLLsy3GNChvJsnv8cU4BWJnoKwexaM' .
    'DOkaGgN+f4aMaYTJO2XifEOPGopwD76LnGLt9rKVH+V5xG+3UYA7N4RhkBJjbXSPHAr+/XtaV98/4OdcSeo04b0YENCv13RZ5KdlMj8QyNuYyzNI9ZyN7To3' .
    'TTzf0Q5g2x8wmQ8c4GnM5T33aKyTwLilIJ5v7xBl2w+koL3je+ZWrVGlBdZ0tlG4FNGAdIr92ndVaZmAd21FfO00xbsbnxSGRWU6oF0/nmKKcj6XGm7V5/Yy' .
    'I0rQZ5FOrVZXh7vPTs6mPIGKOk3yl9EAxGrmsf/oprxKlj8NxnKD3g3dlXvJL0Ye53hRAIAwWX7ZX6VMl+BB1vwODnkjm06E2vKSjusIO/9jd91SJ2YTMRFv' .
    'VS7KcdAsOYcUSeIMX9Y+X362BTH/7HEMGJBs9oUtkcbivdeC+5vHBY0KgHVlFxwrovMAWi2ixIjGo2ybuluPPZJQiBRH+cmZ0/Q0HDQTiYxAKIyMncW4i8/j' .
    '632Sis7zcyu9o+i4ML+ThA3l2vxH+tIVzG7CQg2/v8eP69HcMu7dHhubhNpFJn8P/usRG67sA+uyvhEuq9ID67y+0dI82/0eLqtkZr4Fv+tq4Kq+igTqdrj0' .
    'Spi0Hrqk6lY8t52razFNg2zwNQ/1XndbPI0zt1O9Y1m8K429az13cbwjN6VzsWuTDF/vDWVL0H5yREnYJQJGCbbaemH5gw+ohoThXSQ8sru07faJFj+rFl4T' .
    'tSNeAlK3+j2SVryXKKLvSXEzZaj7AMezSK1ia+Pp3Y/ilbXss49+Dg8T9lcTgkmerq4RX/QpPe5cA8IvHFiTGK1s03MdfhPdSC3T89x/mRdjxKdzylCPMwcH' .
    'h68My8wm9QLJ6wzHJ8n45sQC7ebTB36D3KcLJ8XD+ubECA3sg/C50elGBkL09V3reKK49Xn33SBD6MKyMfO9Qko6bYdeL4oD7EHphJstkH9xYGAqkVBSh0+n' .
    '0teIcGD+tkG6qqPMe6c1jUMinyOmTVcNuzbMa/hMovzOwmwjhIFcu8V0RLFqnazsxq6ycmjrQxxbqyhWbatod8YFgf3phPDMP/7TNCzbTA1a6Wwzdc0QqFky' .
    'EW5xrenMwh31BrQXbYEpuFJI0W5qZChpSjoxZJFuMKSrX1IEKZYoSauR0Wc5bdIpXGWRlWgG0l3+VCctyQpiUEtXJAu6KlOgcNGk25RKH3/Ick5UycnXJqa7' .
    'gF9MCM78IzSz0PmcoE1Pkgi/eBqMUKs0K3tAYZs19SSwkDTSiUA+WyNn+/NAK+mcGC6EbpEF2yYiZUW3kl0nHDO10mpVc+4FMgCzu8BPFg2seYDEs8G17q/h' .
    'EuOoGmTfq2/+Iuar0N2PvM3lChYbHJ3UlYjyKyqjbk1nMveBY0Q1aTfBYsIaqKzX9hAiX7o1TxYsMrmLaL6t8uVsapKMIKh3wuoOQqi6oNf2LCI/L9INFlla' .
    'TI7eH0DJKUUYTiVgjzQk42xNkWPyrpXAKqeH4g9pyO7ZauHk/IMle9vqZAHHg6UC2xrHIuEDq4QlDua+n9JT7lCM8f1X+8VUckw013G7Mv0lfzgmDR1J4q2Y' .
    'bqgH92T+Kx79T4/b0XaMZFQvfszRloPkzxh3vB2JoS3jUCzlfvGVnMaNyQzNyZir2uTsDbWryXFWZHkQ1XTDqtrspCm16/WxWy4l5OFfWWs36myZo79QVu5y' .
    'UNmHVpR/NUyvJ2hOplwPKI0Lrlf5lQ54Cqmvfpouv/8dw7BMxhQ7yOczufpJs/yCiX5vJj6Z/IKKM2Epfp/wPnaPaZGMKn5gRMV7vVqk9BrooiKvM3vyPqUa' .
    'InfsrOOIEJTZqtHU96486yp3HKTj2JQF39IbouGY1RjS2oug7hgC39CmkdX76hQ8I6+jepLFbhcCfc0HnckfzAYJ7XgzVoISFnw9qJAZwucAA81+OTEQWhqi' .
    'hHg1ETaIGKRUfDOGVDIUeB2ulOXIzgN9HQy9HiwkslmeZaldDPHX+VvHGb7SYw9rwPZAG1Cs6/x95zwxYyatdfWMgLBvDcTaqxycfJKe0oKzuNHRui1xdQX7' .
    'eGJWHlfTVtZ7UBljVNNX0c7eAZG4fI2kP0woK6vrM2v9yb3yAZxtQ+QSj2y5Zm59/9uPOn0RZz6pMCmraY/pKeeGSBFwYmSqokvlEWQEcp2jk/ud3PlYq0ph' .
    'BONnZHM3eq/LpP2eC7zw9yE7skG/q1+Q8fkdtJGiHJyLgc8pnTUmGX5TTVFHOllzKVFLEUphyA59buRfXDF5VR1aRyFBrld2xmJSCeOvd1EMZVLJ7m8Iw1Zq' .
    '7H9aPhYmXVtNcUMai5s6mOBqkBynN4SblPzbhcSFS0M86W0irl8vLSkZz4X4TcNVbII7iVjjnUtswjWJhMvlTSxJYzI2Bd8g2XUwQdtvdtW9tRpHq2bVD4g9' .
    '3bZSRlZfDG8Oq7VcMwvE9mtbtqwvLoEnh11uMiMthi+FW6EoNi+Gb4DVng6oA7YuYSFnakOaG2m7I+lAZZi76Ri1w0I3p93oviJBa2ubuWUad2m1IKS+Q152' .
    'NetCpbzDXrdDwur8vml7R9ZJ1zY3gnKP6OmOaXuEfwuHi+5rfu17vqqFVte2jLILj0LobXvte7iKVqvRcYQyv9KIgtR2rLG4gq6J1rJUt4/o6YNtfYx+f81Y' .
    'AJsM+8p7+4TImsiZD1uZSSstwba5fAP7XhzPyQhf/wuLyCUCwaYH7/g6KZ7ysglAvuNggRN5nc/4mgwDz9MD/MRxI00v0kvHAQDzFSgWkYcDiXP/muhhpv8E' .
    '5gMohk6gFf8wgArq7HbO79593saMsWN8NIPy9RQgsoCkmPnMLXbH6TidIcwdJ83pIQ7YMdCII4mPU2iA40xzkqsh8MiZYagENJSnyJFppCQ0mIcYZOipxMc/' .
    'aG3JflSZkSS/RBNXO/oybIjErDuS+4iWMwSX36BvhsiIxDpsl3uIErMEyaBWr0leBwWhKF6vSZYHBV9XyK+GoEhElxNtezI6SYY3pms276/dDJI2HvgzyncG' .
    'onwQwQG7RgYbCZV8GQ+gI++f1nUMsdE/6ZN/Os0dFyMQt69wPPND61U+JfNtb6SDsfGa/myg+0mddQlpTSqHo1gn3fueRQkBOIKZFVrUaZaxgdD3rjWfK/+T' .
    'GEMLVt5vETnVriHnu9lG2hk6j1D3aIlhB7lQ+O3g7Vl5lt3yg3jNDGy1f2+xiZgqQ3mKtKPHTcpNa/fFGZYTB2r5M8ELN3XWgZHGRMysLaXfa39kSvCHz0Cx' .
    'gzAA6JbjcNu06RzRKspO9PP9gzPFYfu2ycc5QqNpj/An/yen23zitatlT9aTQA/YjboqP9enHsZNiyj/dRJ58CmXQCe62ygr3EmPYja/dVZID5kfs8B+Em3m' .
    'fqtAVFdQiB+/38KtH00FEqZ0t3FWFoVglJ9vF1kURU6WnwAjk5lhOm1OT2yb9PyaG+e2tATe3RWPWf4EtmQJ6L21PXjMj5J8TaWfoETuaKW171NrHYZN4tC+' .
    'xXGjlPCY6PuGYDye9+p7eyAwTj+yU0R5U+wPvurzFlrQTL5IZKa+su6ffULV1Q20oJ5AJZm5QJ33rQ3wxV8SOJtvepCL82I4TomsgzRjUeIsg1HzEaasMgQv' .
    'n+6rgz7tc3Qm8xEhrDLvRGs+q/vu7QnO8+M0tMHim+9YnsCX7cL35Xc/IO5aIbVbHjG41fv1n+t2nsA+qn4nZct2OwMm6sO1WqrAPp7+Ku/Ila5sxdzi9iMe' .
    '0v44kLK9Zz2jlKVQTGzrhq5/ebanj0iTvsZRyQsy6QpRP8TwSg9R1uShdYuWpGvXp7lIK00uk1Ih5ysXzwpEP9ERcr8SVU6n4nDsEPZ7RY7t8nZxJgGr2Hrr' .
    'hBlfIfyv9dBND+OASnC6bUSFTvpg3XXIeQ9jGxAiXQ+4An5il9w616DZQLUJCZwdvX7BoB08nJ2wfinov5iUc0hFlddItXQpnCmz1pPEVI6V7TsZbc30cMwp' .
    'J3dvJXwSbd0ktWcZXIWMEcon59SVnoglVC8HdR0ffMMGZf7i5h2VMPlo2Hykr/4L8pfpE4ic0vx5tuJ6Ncmu3ByfsO9CC964X11zjc1CEmHBIzQvRbtIPc+J' .
    'Aa9btUrTP8AOeqIRKmzlB0ZCKmB/7Y8hMq6dGE1/clnm8xVekCFpLu1J1RxzaE9CzIfLihWcWjGtTY0SXe7SeiJNjW5f7t76dTCYOPDlN9h685Lv+tXmHHoR' .
    'lCHrmzp3XgiSG3nVfmZAEpU56Jo6v/rxmdQy5BP5ZUFKH3Q4+BF84kmHFDt4QTrg0DD9MvHiRkOWNqG0P/aW8NcteuXhdQZCSoMz21scdnrpin/x4DlQotHY' .
    'a5qUan95v3tKUEj1epm9v+hQeOO4CvFK5zZ5GxCzZ7hyl7HvSdBH/BAp0vH3587AYC+7pyQjjfgpV4TvqinEa5nbJCGBxGgd17OjSr9LKU0RVEcDh+Det+OM' .
    'D7OMZhvAV0Ec0a4sRJAZ8WcUjdM6AL+KuCwhnYZAJ/cPDMO4cx+xO36EdC5PVjHqhnRuGUtWKO4GTEqyzoK30GyEd64qG8rSxmYKUfOjfrm3ZS6+Glv84kbW' .
    'tlr5I1GzdwSGm8FCJt+sLuxSc0vmpx+BWmRPy8aDX7YxAYfTKusa4ZIzP0u68SozpgWsG7mf5hZaChmLp88qMjUHkZuJlaZv1gCrEw7HGrMfLaYbjoWYAy0R' .
    'tBu3mxj2A9iG1LbAJDjpdvR7Wvwk6s+uKlhNLANyosD499XoSQ9q/kGbPkPlwegfOVkIu6vKLQh1sAYEmq3CJiNyLD6GwCC50ong/UbN8ODKc5eBwgeW49zF' .
    'w6/nNDGLgvOkicInOxCEzA0xaZpNUOGE2HHjw9dXwj33yOHDl1D4/fPc4R0hx0Z5xlwoWybq0thhd8bzJgKdZnKCYRLL29YYZHPG8qRUZ3UodAr6Q/ZcOe9G' .
    'aBrqGX8aSF71t9RGFeJSaSgzm68lkReUqIMllS8RGbq2Dg0TqmrO7YGDOY0LERmhNp9iBJqq4N8DZgEXcyIvGNFMVmWYewrFT74EVqR7cenPP/WY4dn3mXaQ' .
    'x50p2VMJrvUbbWgquckPh/gjCdnVKa5zbZkYKr2JD8VLfzOzMcLtEpoa8JOWNL/qExdxkpp1vs59emubzHvGKh38eptOu4ZzqSDI1FkUy216rruarHqHhUKo' .
    'mNRRRcttvnx6mkpqx4SQgqjUacXricmYKNQjJevnpshpISYrXVnGJsiLFhFtS7bp87eknUBz9GOMRYvgtsOV+vVbNEagucEpegiGcldJlvweX9DEKJXIXKVv' .
    '3/bo5ZF+d43mnLCC3t+e6e8S7jY5yjFvW05bBeWPkunvHm7NYptlbwZa28tPyfoazS1hIGf5BJ+8mS23lfofviob29kUZC3mh+8plJc8pespjiUVz0lD4sI/' .
    'Jzcka2rX/zEvhUsb1YPhJ4zHzzwYMmO+THn0cjC1KJu2QTsllAXJAjbAPTvzIQYIjwr7fTshoHD3zO810kCgxYDBbkA7hDn+nhC3FbnBKzKRCf5aN0QB4MiD' .
    'FvrhbyhOFnKT1lYXPKRkhTn7aPcckRvLKuO7FQk2gMPBIeE/nnzpccGyYUK3Jic3ZubA/zzrpXMuGeYlPiI7OYxY4qot47TcWIziqmnitKK7Zz6n1S5gJ/Sr' .
    'rq8itzDpcMeB3+XY13KTOR9X5TOYcHTtHt9jONeVcXoX00ufsBUr3J4kyGen423Y1iTML6crDg7bucAyhoVwteXx4u8nlQzf4BAuGr+kpVLQuMTj06qPnI++' .
    'tRqjSkve0tnKyKHSlikqAACD8Le/pbQDxKqVMI7nE63oBU8r7PmUsVIIRRWnJwEnAiW1bkYjA/Grk0WF4HTBlSlECmqe6j8Dz5o+b8G7bRAlnpW42UiLyv4m' .
    'V5YRRQL2J5CfdjzUBHr86rGDtvw6YmqofEhV8aTa73aOvXAIfDRePL8EcgaD2+K6gxqhHRo5L3fY18OUFw2DvEn/S4R5x2Mw6gS4P0NH9Fb0BhDlAHwT2X8D' .
    '7IkAom8c8lbcj5L6RSj6VihFktzyj9xWj/KSKP/Aqkhf8pFbvn0QX3sL+8UZe9D5ZQu/XRt/ULt9yxn7JfQx4SCNEOtoLem5OYYce5I8aRI75nmt+TmpeS1m' .
    '8h8kYZPHND+vcV58he8Y8x8vEwohcwKatACEWk2cQsvIQoTIy5xagKZv/573FR/yaB//aPKVnu/3Hv/375Xof+BP7rPy3vOdXvEtaZezAZ9TAb9h950u+V0h' .
    'mW4Hn7MBmTaS3OFUls5rZsuVfJtUEI3PUC+5MjK9gj89IskQXc+AXx8tOb0y8ja4S5EUS20bO2hLnbT7RrE7SPGWZPsPBqljkyh23/L4/XDXu88hu/khz9f9' .
    '8nDT9s0BA8kG8cn78QYD5mkAN02ZhnmvKj0vTb2qeRm3BhnNBrd5vX+gWeU13yDjNtft5uHl7+Th3+3h5OU25+HW7THn5fEPup38vTzc5rJBtzWmNV3mNSDz' .
    'LtPb7Jr4us19EMb24CBxdAWK5XuKP6U+O72Tx+OAMiW96hO52ZOyGbkq5QA9pTL9gKrZE3n4uEBoHuX8N+X493yeQHiowHhoeN435TzJuXhFx02DxL0Zh5j7' .
    'k7Xwk5mwtTvHvRiHmdi9u/A/MLN+chfjuF8gfAyaiaRMiCRMoJx5XAh6JAxamEn4B4SUkTNBjws1JKHPK4jkTYgkTeQroTXPoSTPNStN/4CEHHHlObSmoOI7' .
    'mjhRDCKxAkKM+Lsgmo6JRiOT0OKGkOnGIpOGTmPP84n8tBAhv9AzH+H0aY/8yZN87zT/H3giFJ6SP+2dQn/Son4fjX5Djx6hfp7SIpzAE1sdESMdnSARW8Ej' .
    'EJe8uE261CK51L64ILm4lUy6vUyWuPwfXpBqXSbdSg5aCxVxGWIDGVoDY3ELDxQLWxUPcAP/QWssA65i4QFQQZ9Vvb9Xt19Bt1ddH8iqr8AKVNf9Bwq9/eqs' .
    '+sDi9TciOqVyUaV10XK6t2Kit3WiYjrRf7BervTvHoqdA3lYkh1+to4MOJ5so9lNlMEgQPA1rsY0wsSs8iGUQXDjXdSDPu82P/E270AX3PUXePXcoM3Pu8x+' .
    'naanGrRkabTW6NXTc7BTNLDz1VbpaKC/feaIPbmivb8i+Yg9MLPMhn633UkZxckGRbmdvmyX3ma3rB3lH9goO7Xv0pcR5JoahISi5oTm5qCGmBIYmOYaEITk' .
    '/INc1NAQA1MCb6xwRh96exh6LBh7n3BvxnAsRm8fmH+AZU/vwxjunQFHD3uCnVaMDVecdkKfAUtlqnVmKCHAImHKImCoRXWmqdghvO1zKOGjKHG43aEp3KEo' .
    'rLkt8Q8UD322hTs0CVDrhFOC+pmDUJn7U+oIhOtQhQlSmP8Ban9QinAdwZrstuNREBkwSBZIdrS95rgt67h2BPwHsmRBR47ba2eTnKIf6CrH6JPHKh+cZ6Kn' .
    '8XxI7VVPdFXxdE/tfKdIz1iBaN94Mm54WG4y34HPaEk7zyUQon/hRHfg/kI8J5V0bC6wXCWu0I0cJmQthJm5hR26mS0kjGRVIqayjj6kZDUsCqXfzM6xzy6y' .
    'z90INaQLLaY33LD/g8W52Zt0oQbQkzkMTgHfVcHTFR+OOQjG/AkGhHP1D574CnBgzEGxjXh9/new4HeN4LD+eLF9eI19sf7g/6AR9s6/Dy/2YEO5Us6uXt9u' .
    'Q79eTvmgUnmj8kBO367+ZkEM/bFpG2CLHfnUFd2kR/qIfb3KE0ppnvG1bqnnhKSXgeRk+WW+PpnuC1v/X4rGf+kaKfW+k7CntG6A9t7i3V7a3eJ2t1OApSEE' .
    '3kfFwFOF4dPAB4QlHoQhnuXH0z8wHKj4wIOwdEXWhH35rZj5GzlT8UXTFVYTGdb1JfMfICv+foHVdN1l7PecVO6BIyVTpxypjwivJwuPGFEnpXSW6Nkh2bt8' .
    'zhbL3bMfFU4cFUsUts/N3ssV28u2T/wHYsKj9nu52RjcQUbIo5Huo9zukchBGEZB3EYYyO7/gDtyFNkoCGO354xw+iFl6KFnKGX6bJfwrIdwd3roH/SkPEwT' .
    'nu3+Fyu7L0qeq+r8UcfqxNuiyfuh2eJU58xa98Hq7KTJ22KksDH+wHYSzaYQffKwYTQ+LtZd5vsN5fgt5gjl2z1ephGADj/XFZn6XGLou/+4xRO67HikKdxV' .
    'Krxc2qXpGHq0yOwUtIf+axKdefLXntNiUNKm/oU5sV8z8Wazn7l+0sXgfz1yztpBfdr/9QU59wzK9fwnN+jcpx10bX8b/XfNIu9P8bBv1DF36XFxKXfU8B9f' .
    'Fk8JEb1xCKNxTyMIPQkWkbK+VtUf4vhD4n1D+D9ay1StxhOZx5oLlprHlwrGEq2YN+KijF+NbhyN4hxvXqM2jC32wNRSAzMsAvcsMlLBLNQQhURYmdpHAe1C' .
    'gFEmEUTWDoMdU8W4Vdo4A9pVxZ0O0zCRN0IikclgEZHgSaK3MEKBxZLHTnyvOvzFOq/OEoFHrkMpyFsViWzz/6xRmmVty3z/w2RvdhfsNnWbZvAwD71RrAdK' .
    'Y3u1DzZbrLnPsVlMd99U59Vzb2LZoKk/Omz4Y3PXovzCjY8MjK8NjMRF4f7FX1tL7x4Qf7T2GSt1GHifm96kyl5tfWpRyEpdzpweNq6KoavEU6PuRGTGLS56' .
    'kPjmOHeeFk3cKTV78ydHle9BumuOWCrGIfWceE6qK/rcMTV1zuE8plOKpOsjSK/7KhTjC2yDDxD8YP0AFmwF+OLfuKaybsBJk2RkDD3428Hp1CRJmcaEfdNg' .
    'nUbFJIFtfdPQQHVjjSPJmOoUxtnYzvT3AO6CbPQHL/0EZ2iTU8cB41/vz6fvGqxniUpeX0IbgEXD8wemZLXP9zPWp8RT9bPP9/en93PNswSm7conUs+Qx5Qf' .
    'D2GlbT3AAsBTb2HrW0lUw5kZG6OBacynitW8/sUag8WpYRRTHZulyWGEFZNZE+s6tmJHfUAlzqL6HbPG14IFxxxL47qnxPqtGsOyjsnX8mN4EhBM00OMH7aq' .
    'QDnwKO0JhF1qehdipR4m6QmeZAYTAr6xNHotwz2EDUhTEiiurIYq4lNJ9z/2h0k/UK3iK556XuXfX37s3te2axQlnpp8eF7t3p3mX1157n3cXZ7m53udXd59' .
    '7F6e1iaYFN1rdLTXatwXmiaeJtaanBV23GlcFoxJlMoEq+v2TXqM7vPqBhfIqJVeSo7J5KsFl41dSn7KdFqo7V6e8/Qd6I7qACfDBDFVSWae6EgM24b7aDrD' .
    'rMZCjy/8Lxdlk76LhL0Q4S7H/RfOrY7DAsYWLi9CrY6Px61Czy8X/ZGSvWCFZQu/hZYiVFxBplFeSXBIwt+yhbDC17o1lngSaLykstkXJRB4QhaS1XC6N5bC' .
    'ErjVN3C6usKwNzV4EhYlvOcQOWiypGS8Mqg5EBcl57zgJTlkaLKXtxKD86KSOBSqMKECX+JYErciOHNXQ5Kit9gS85KXQ0O3l5JzkjgiYqrfWILkYdA8OjvT' .
    'HD9VqlV1lKo5eKd2Tv+myR8d6hF8IcVNkr3N/9K/PcI/PJVLO/pLoHeUeiYnd3uWeqRHcDiP9PaL9GsyfmKWQGAOE1sAewZLYG5CEL8r3eS6sjXQT8MOjIBV' .
    'YjQrMKPVt6rz2qQ13TeoyqTz+jq906Qy0K9t1F4yi0UDHwzMnkCTJVNiVNI+a4QVoIn/EwUb2s2sDie7MURZ9UGWPzYENNNFsZZihoJd546tBHMAcDai3s61' .
    'k2l65FfJVg4JafyVo8L3IPvYxC+jGpytfP2xwRG7KZH5zt561LfqaDRPAb5UZx+PufmRKfHf5jVHHLkdVt38MoQj24px3/tRG2dQi8WVLgX1KruRY2/b+9GI' .
    'QA8XND8c2d4Scb6TutIArCA/GfQoVzefIBksTM8IF7fAaDc0HBmf0rJav/NePjHJUv6u04C6ktpS/09nkt18uZH6hb5ITyM1euSNJ8RHLUZ0mR+z6mxoUSNG' .
    'nr31cgvsGGqoM0zMsg/0iNpPahvIyPQbak9aiI+IDFoPT8hqG4Zk/ly0+uBBT5mRY12udf7gZHqBdIbc/nqkgRB0AQbcXKQGAbQQQfq1mS4Bnc9jUZGZY8+d' .
    'AS51rln+tZ1RT2NzJO74TppXquDJ12ITXQ0gytTpkhfbhRANEtVLZ/c5gsU02+AXquKp+uRO0ASE+PVNkhj4JKizoTN5p37yBlwcYfxsrJgslpuN/jThC+yG' .
    '4r9xMu4ShPFTdTxG07gzOm6XthLjDYoa1WsGAMUXe8JpSDfGLsw1lTxlz408TPAuxsQlSu+PDXH3vDLLfJCfCavY1aY780QvyuaVu9gP5InevqtJZGYx9w2T' .
    'Mj8WUF6BpWVpQR6I1c/Er5TVFGSZW1DQrD76u3PN6MgcCvWDDT9gvbnL6Hf+iPpOSRjluWUX2EhLgdrvNaMufHN2/89DNEgoM7TDT392fDazAIJPyEO0+V+n' .
    'ACc/2QGRc6atOmdYWVzWGlrj11Q031/9ss5nc2CprK+oRnh0NSuMqFdALMuODjaC3ZmPycYJts+m2fZd/FpC1OO/nAxZKn2XIa8wM2z0RBxZf+uOUTmIMulv' .
    '0WqPTwhrUf8yZHHM9kKzvaiGXF32Bau+skPPwPSyzbxcqYYIhA3ybpLHB4iKVcr8Z4yCFB9GHrAhwDtEEeYftzkoyMsbJjC0GRdA3q8deJta4I1xEOndIzy4' .
    'fmMkjogSWyUis+jD258VcUYX53iOSgRO03/qE0GXtTjAG+FDd5bFuzAw4LPIm3lGF0HtAD5AGId2ce6AGk/UD04D4dhPTXgeh5YU5vnz9QthZ//F0HTXxabO' .
    'PB1z9qxlIOk7bAf+xTP550B6c/KZ+QwWLkHynxAJgTLDV9P93VoXG5eXOps9gwMTqraulUmBN6tr+b6XPxcdzlR6qUWDe6UQgq3W7xOdlKtl+rvgQ1SFqTVf' .
    'lJj5QDSmgEpFYN0O7CRcFWiizt9D0ehvZGB7Ekx/I24AxIF32O8pWUVH9Jio16Tbfuj2SKPAKNmYV/RpR4UwPJ/f+43gAdub+1h7DdNCPni/Qw/8m8CnBiHK' .
    'GcHYp8P9IzgN7H6W9ROCdu4xWoYAQ9NsTBBT5c1EGEN3AzugnwH2ZQbhHOFWyRXiiRTzevNJFPoJ1uIVXqXyF+6cdwZOfoA43UBck8BAyDT+BwRezlLDezd5' .
    'r3OEoAdevsBUKFzfQBMdp3gwwh7l2qxu11GXnu7RTMK6X54gbWFjx1aGSdxFYqvkFSXr6fqLfPOpzCXyyvPt5k/GLKObOMY7pzD7sVjY/ZJIntHTTM3LCVjQ' .
    'Ky6dhdWFt2cpdWu2k07VLrE+GBorsUOhpKmCsj4LQjL/mEN48AjFI4tlmYXW4ty0ox5JIQsxGljDO0HsGNiJIFBPX/38i3jyA6LZHQB5tpgLiuIvczuN93iF' .
    '6PDchKM5g4CcB3wAmxkLtpdw3GOFdvKXf2AJusUK5sd6YC2DGIEFgv9hbzMuY6yIxxm6qKVow47uudruWuzB25o56+6O2sJa7rmMau+ayu8sMkdrMW7JL5j8' .
    'YI7R+iGvE8m4sGMaLcOsy7hjuvjmxKO2agQ2pe76wrMEmDJZrX4n8I64Sgc4GU2vvKjxf70/XuveRNE+vF196zJcRzG8RV1q3zx/3bzSRWv9C3Q9/J/Hgzkm' .
    '7qX0Vk2fpthGpV84De42DN9l2MaNdG42xwk16woj8uE6thwEODW0g3VW/fTYnLoEDDbV/djaBNx1cFkccnGBFxzwdRkywRfxZwgh8TJcmdWBCPGn8rWcmb7X' .
    'D8Zm95UYBtFpYJA/vQUVooW9odL0wf9eo5ZbPvuZOOvXHEuOks8f6zvXSFHMD8/rkw1LndS4kOsPL0i6HtWI3i+sH70OrM/fboierL8ObN4Ovh6tz4u+3m4M' .
    'HM2LbsL70JYKZV+ptvqnXcUNu7Y6+4+2xbVcpwr3OsQE/HRDeE90my7vX19eE0+MUkiErEoQqYD8mbgeAyWeWK6wHpPgV45Sctw7ip5E+S0dcIeLTkB9j+qf' .
    'JPF9T4mB7/+VLDGVPA+7vF72OZ8AN736uVb2nVCyvgo3P7We/Fm8PD+FIO6SQMoHsyJP7iKSxLMqDyPnugTDR5EksuQKKccvTp7U6o+6o8seOYXqv9WmM8sW' .
    'OeMfyaIFwmhl952K1sJo3XFu7s6yzi3WkipFhvX6iKAPLf1i8JaARyprztaydknvCT9Yj8mPYQ5cO4gKLQqJZg7ZZ4osjFmLiNwPYs7fjIhJyeP2zKdj9Pwg' .
    'IEwTfygqKiJ4KBL5SCNhzGbwzP/tw/F7f5FpsoNrbG7vR9rEeAfXxB53+wTT4u+u/UnOsfnfzBAbXLVGHFFxNWvgXCaRcdxxm9FcxtUc4NEbXLGmgFqObVb3' .
    'YTWwdwcP1uEtdXuwd3vWV3DNYbdtALv9q4b79jC0eRFfidtpMo85TEHpabJHosUFsJinAPrcEphQCslbMAK236/QKbieS8yIeDpm8GOMmNHggjEbmQCmLwco' .
    'XU9nA247vdEmpfBkaTcZUAfqB5lVD/k/TzrWWfbv+Do+TxJKrtEbFFXBbL+2WOO3RXG0vnJG4bZtWxdKQ5YbbhLTCZWLDuwFV2UPVQiK7FVmB2dXVgQeDIoK' .
    'VpQH5e0L9Ys6eMZ5IaGLuf3n5W2P6PFv8BZDRfaOtUfz9hBDjLP3JFJrrrhswD0vVyNsvsI7bzhVx228rGgmwtOoP70iKm+2oC4nzdbVS0r5z7gkAO22HyN2' .
    '4K+v8e9iLcoEg9wqM3I0zsQb9+9Dg0tOtETgicGnPufRl9tNIsYJ16eeO8ZVop1I95cyNHhXn9iHnXInJHi7CABG5avbAVKsHaDa6/ABogqDTO1zN4Wi3g5L' .
    'AZr2GdO49/2GCd9yo+kxTgNBhZf9WIW8lZfJyBc+59it3SirFipdOzjP55ZlzJK/XS2Ggfai6UfZkk81U5sj+4TYkd7WBEh9WJLOy3iD0pAhB2gOHeSHmqV1' .
    'yrCTFhNlxfEdK9m0RggXVR3wksUd5HCS5mcUxIX7TN/+CP2cFel7/2PyR+ndqFdYfPZdwXSkd1ZAPGAzjUgv9Lw5ZZ3E17A54rxt8yLUgDDFL3Sj7UIvxY8E' .
    'fox87P3TgmNiEp70xZzji2PC4uNtnALWbOyL6w1ujCLWVryCvmHAQ8y6Ko7BvWGgWx5BdmnWA6LRGjhALxpb5WrO1Z/zmmYeuKTbbniAmlSjTbpxQz/jkmL+' .
    'ZpnnPMDJZHpH1s+molNUNAe2+5YU/FIYmLy/UADBYqLza/COiWI9AKrszhIxu9h/HeYeJds8zw/J7G8Z9CaKr3n27WYZ9AyvHtmuJpe1Pi/p1J6tBpc1H4f6' .
    'PoXetBqfFdee4TTZKNqjd0BoEyg4VC0Rd4gYP7AJcMAk/kjdH45LjK8ZlOAC7xXeRvQt4Qkf5toqSfwtBf9J2Bbm40KCIPnV7OUSvrRNSswfCKVEBFoi44NU' .
    'ClTcggzmJaRYgd4JVORZIqIIeS515VhURS59dgnkRllURXlWWeB2LQ6Ze0ZW5SoLce29G/0zoH+0NHzbN9J/tGTAykUdBRPlqXT413B5sGdkOJjVmmZxMpuB' .
    'CuE29+4Tp/sLoQfr7y113iQLXe6ibQjVt1rWtUEPWupWmv9t1Krrgc6nLK3IDbkOukbfb8PPy8yfXf1Q4fISTHIOwJo0r4d5H7vFp9/usrVy7YzSYUOKMJ1t' .
    'wwyDpll+5qxf0COP8Azw7E/0w+ZQX09s9HCjnxZQ6MnY91SZoPSBXTQwZyqUQKqDICQntAFARnLmDiU2xv0ctWoEuXRhB9Insm33Wq5S3teGUg+iNWIRlXQn' .
    '6WK4ijU/dfhRSE9fRhiMsja4RSZYeJa5DnT6ryDe3p4TGpsIXu8CPW6vk7jdNwBhG4D1D8sLYLh5lxji0NsrnpPXoAgb/MzVDcCEcKeQtnJhc9hjq9B3fJZ6' .
    'twQAg2MGnuK4xM9z1q39RutNZS0VnKOuydlIIED7I4/mfMeqMjW38viXe2CHSPtwD/5vb5P/4I6dZrmk2nKX9bv2YqbxquhkOqfJMzd+IsSMj2AnOLmJwJbE' .
    'TruQhLEAOfhNe2fl0qdgqvGM0nR9aUGWoqId716zxgAwYRsRKlb6PGYkPb/TCJvaW4Tgir6yT1uwDwOodDZH0iNaZUjvfYp/I+aDy9SpXakl1lXx4xzf7xXG' .
    '6gIAu1C2CANbCPZyY3V5B+Ny24qhZJDajKpd3DPaiBo3dLLSP92eVjxsoIfdgJWo16rVPVo6ktpdpo/ZoEVTHUHYd1hOu4o6M3gU19Q/hLUytt/aH6/5Pxbu' .
    'MxzLNo7juL33JiJkREY22Vu2PMimjOy9t9yyhczIVoSQLWSlbLI32Xtvz9V5e1W/4/o/Lzt6Pt/T0RHxROXs7vXnlT2nIsSUjvXjqdua/6aJ5w61SL7uXM9d' .
    'nW7O1MwSaxwvOBaVtiKlIMy3pH3Z/+RepncqcIQ3xW00GKjN/rqaf0NZe8Disov926gVP8cLjdD/RnSDHlfw2/c+0K9MjUrGYazlzex5I9Jxo/b4x0uttZEW' .
    '5WtOs82R/1JIAo6wOBpQrEmMeOJRxmgbSTiRMTKPvOdnHqj371y2n02vt/1c0WY2Jua3TqRGHEMkvz+YbGDDO0yORhtvy6tXvfTm8Hdlbkhvw+KLaLmcyNyl' .
    'byF9lYchh9Cvv3NDqkNW8it/H4ZULtW/6I2Mkc2RrY/Ij1z5pZ/TIBUR3af/90GQJmYmfSW53TXHFE3kqu1XGD1xKj3mf9hh9BqpFeQPThnW0zSCKotJTtSV' .
    '/QSnCv19Z8huM9fIlq5iHGhsZh7fPnhWWUack8qoeBN7s8zNmPuAOK3s8qtaBfOlYnFuKnkqcy7h50q1ywt1WqVev9iHK4pMvFdXzG8FlFceXDG+vflwTWBa' .
    '/p3ZVmY5kNGpNBnvwVWtw7fMVwSWZymkX5lsm+yu6RprLAhSw5bpJF3xSpI/rWIkuofJMCauFOG7yjEGoXfoE8iSf8WPUqYhODjD1y7vIsaURyc1JOxANpSo' .
    'wSfH7aoklyQ3RFi08hIYfqr4Vc1a6OvQMpcPhsq1zlE4CVVSm4Njkn4B27mAIAdsTV7+Y5sxR1KCi517R7JNXC6bIVtHof57F7s4FnGHPQkt3T1dQZ09CbZT' .
    'KzmBNfmgM07xKbMD1NKI9foXX1Ft2wloHLbNIuqKJ5FOEC0mD75s1EfWm29EfEI6mUGvsjNotSKiIflmR9WFYGBNXUNq90PXGiVOVLdxVE+QxvEXnpTKIPP2' .
    'U1FdioH4JiN+PH+R3RgTrWjk9qBUV58K3F9ybkrrA8x/+nfoVDCdpeh7R3cVnKRwbQ9tiLjtG4a3+8ff3xo1B9Uf2gzz2hNby8RiqDdXi2oKRpRrN8rp4I+g' .
    'jKZ9c4hOMe4PbDqf3Un+3q0Lu95Jnls7CqWjPqKagmn5BP7QFkKlODyapNhiDKU/2gqloJ7am96jPqRiDF3zUw8JbkPVEdLUQBbv8AsMEdTWQux6E+LNTBWy' .
    'cP7jkaLGJ0GrKZ4Rc1bKNqVb+sWgcgW6pqc63TK9yuqSgjW1jCJFVloT5twjPCUmg1Mi6tYDxVwvJ7SsRRyDEPDyrrxmJmzo6Xf7mi7835xNfHTFRMEMdUQs' .
    '8J05mwj0vM7GQXGnf00/t3nT3dRvd1G3wTTJUP/61/X6LAOzrp/y164/kg7YyvXYrLud/pIBI9Ytht/U3unyJy+WKeKrGZdiLibHPfn+DAuTPWCzc13Vu42j' .
    'GRunTXXDnw0fp+75q/IooYLC6Z9FH6Uv0Btj2RkLGRLCeGd5mGDTiRyMud0z78OsY6tUcQ9UA2lrk9njjr5z0mAEqzWUIUSd9Uvk2NeMYTYJslz6ZmYG+Z++' .
    '7WCtFD/7boX/B+Obw1gdy6XYbTWnSC3GH+sPqWH+/l1Hb09SO6P8srzC3n44afUNCMv0TCZ7V5S1jZaUTCqx99vq6s3QfzQ6G2Yhr4Z3grWDqXSoxsI0tc1C' .
    'tkniZONOL3utfsZd2x0Rx8lbJfaeHSfIE+zJIjJ35EujI36qcWzufMAoL5+N3HL8ENWkvSon9K++3IvOZenAV3lVK79sA0UOOX+z/D7qF1sKtnlRKVE1p53x' .
    'd9jV6nO7fG2awnUF/gqt4O96Z4mUtrES2yLXAdsfzWnSGS61Ui1ltkOVt1iqf/spBO+f/RJcqlHDFb+k+jmvhlsdRXIhZI99uoyC+YmeO0yUd58Ea9U28umN' .
    'OFnElfXhMs4yyQGOg8jN21iGjeMbDMvmIFzup7ylSA8QLBE79cM2VGh38vMcVhTQRb5/knbFyEBQ3v2L4HC/oPDjLk2BrSr6KtquyqpVQSF1UYPkU3cE7Ayc' .
    'RsR0xyIRufRaTBQXQbmSa3JvtvklFbGIpYDooN+fmp6RLYr+veT0fG+q+bRwDO0ZivmQakGykI7f39i3IQ2/PnUvNH9+4xMdaWarTIRPtJ9xOl6wzbb5zqCO' .
    '83qRuGy1M2l65wXn4VpuoqNeDBYsHS/TPQgbJzn8xe0n/pkmbwb2hyX+bM0XE3xVFwnqgbOyVUqdyPfm6YMRf5ld4UZtkv4X0sqAtKh0H4GHma9JkZ1p5SHT' .
    '45VnvM3crg6ROqFd/Jdbr54TxVz2YpFabGlH/Ma6QsIR+F2Fw5VLdUEz6vlV9AMPNv7HCpQeXmQXX59+tRG8YXdlnN/oPgHZKgV4sjEyLnLPYlwlC3Dzxa6/' .
    'ffCmHKIYS/HvHX7891PrMaKgPaJZ+N9Uji9jf376ICARGewMcC6zowytriG8IHM5kqqzP+ij6T4+uG/j3ChnsocYYd0qiqYeWfTZY/ik8rG5ss9HlRci836W' .
    '16FNE6UFfG2lIe+5beyDm0QqfraR0ubaGH1lY/D9a56Xkv1lc6HqgQB9eDL94i5dAyUWVeyItyuqTLtn7dv0tHHnH9ZfgsmiuSXdWtmV2zI+pJmqSAu07zjw' .
    '0qNnnM45uWl/uvRhb3TyC//hKYNSgE8gg7w3N+jtz7yTMZQtfog/MIpIkKc2/hd/edGOOaM81F3LeITv4iiQf1L7eUDl3JsTrheulc+9Q/5rfn40wFf2IOPN' .
    'bxrLoFcPqGH9X4LSVXXxhfy7NTRgbCXxHXZBtFGPvdQaWMy+NrFbP6hQ8Illo6+z/eoZq+LEqRjZVMtuhtASxKe/pLWt3buwpI7MFbnZtqBuGILKZVS547BG' .
    'U21+tjvW4NDEnFO2xlxh2TR32bxayGI2c9k8tFlz6/Cllvk660Vod8HAp5HUzx97T2L1FB2tn6Zie0QEpl4Yt49++pImXW3BQ8lJ2ZiDWKw7YmtXUvQVSf+l' .
    '3bTNl0Fbg6ocDCSOpzmcdaNWQyyNFvSYpeLNTLZDLEJIpQWcOGL0E1YVe3XDsPjeYlUu1ps1UgN3zNYG6Y+ZM6dvPVmN0Aierh9HuJI+I+9Nqkn36PhGFS1D' .
    '3uX2LY2cJlJG1uMNyb0PNb/Qe59ZJq+iW9p1Ya8mW8qjr3bZoCfLo9vJQ79+sFxFvzqrf3wjOvh48sKwWoSsf4J1KzvlwrFarfOcZk54tF5/V36ILxfJUkcK' .
    'KZ/oqawFJxmObM6TV5xSZviyTE9kiUp6E5Stzs7ViBTeXdFed5srHGWLJaZd3n/mkNIjfaZIdM2jJsfw3DLr5Fb6vYUxswzPS7WThP/keTjlpJl4jU/NszT7' .
    'CVm2cd4qhP9EVFw04KTB7ZYMXqPW5WTt1aBdi1JAmrqQ9HTopXsifPngh4mf2nj/Hjebmcq4t9SZ09xr0d90mUPOZvndpicUqcJ0y/u0nzsGD+wLvN6ZEaRd' .
    'lK0RsvJSxVhyBnPUI+BF1NBFcJjR0keg1wfa03KYxDITxeA9qi93LJ0P+m9n8MDB0QBvMDZGw392PqigfD7KfiAWad/YXydCrYZ9dZLuEWxu/lGNss5WBOcY' .
    'nbxOvQSs2eAR8+oky+sp3hjE2qEqM+zx8AfCs3hWU7XBg4zCgvZsk6FfhzDcukZItVC3Gmo6lrENSIfdkHuq/ur/cSOf6iBx0fmGuvU5a0YyjWg5dCGRJjQt' .
    'R22SKjF6I3EoW00m7ctc/GIo1T30cGSe9ZOXdD7lnl8qHYVtqa/cZ2laCzy9y7k+Mvg0NWci+hw2zXBOZX19fNvkj/wJs4TPZo6K2y/hK97lDGezI4lpsWd0' .
    '6f2JlTFGs2n3wvD7hB/97XzyXFfHCqynmYbyc9D8Iy4R0PEKTxDeFDtjXXxEQ4Vhlzo7fi5AisFGP65bEFrhU8AYHFzHlBRc46uWXZvA5BasXuBeWf/GPa6I' .
    'YaHbmlPj8XEoR9NpoNqyqMtDfbCgosus6KOO6c+KwiH3tNSPwY72ToqqvGhth2+035nES3h7lb57q/UkLOlGth05c+rI5Y9KlXzlmIzM7AefY9kRme9j1wk+' .
    'rn8SL4eb5FUrEPcvpCkxthaQEKkVzg/riTEWkJTP6/evsPYrJdeJMIY+HIUZ+pNTkKW4kmvORl/7JZMQ6d6MRsM+jFz/d5/COfO7AXE754NX5RcpZrHFIbOM' .
    'X205OowT7gffFA0HNrzOolv3MxYmQMmK15CEHeF70lItf0AQd+TU8zBGpNjPCpJ51/AYd/i+9YdPv0woXZTV6iyV8epYDRXk9BRU5ZlwrRu3eaIpL8UOcc6f' .
    'iiJf7xBHivDgXl/FrBMTi2yHnN/giN7YGbs7En4enrEvI/Z2Uj8heD1X6qJx4qdlEbDnN3j/c9yDy6k1ZrpYNk62wPnkwTMWuki63dP0wQGW9P1N5lg6vlLc' .
    '/M/taFN7HI8ZNcSncH8VzKAWo/CVYud/ES4d6UBTf7+e5deJOoak6bDgHy2t0Js0geCxYvz+m0WQVXOx4O9vUd0whN8K1vORSKoRz2B4LeHWspi/a6JiYqTQ' .
    'AzefYT3dS3LqdMiiir94Rdsj7vje4pY041cWt2PACV9caxaVrdCq45tA44m8wvWB529jHfnU1z9OhAbwwVz/BnLByvQmkO6ZeVoZoEphEGnKmuH4WNHKj2xe' .
    'E/b5I/QhRdXg/EnvZl2mnHW/IqZkPXKZJtvp9mcnOR9e6aZcYiXpmyDzuqLwROZfUPeIcvfVgq0RCCJqeIR4biGQCQo4EWOsOEbp4sym9w0qqwmJTT9TnOuJ' .
    'x5OcE1GeyMDrS539jTj7VFktoS1AG/uUipy065YKOVnL5/IXLTG6R5JWx3gK433GRSGMzrwPypwupRecR/+1dKX7srfleaqW4b5/z97u8+vUeE9J9/o//+NK' .
    'Gxfjiw5mo/7oGy27ep9jOV3rY+ZshKZIq6fbSOQUHITfdr6qTOmMPqxjWaigJsUToGGrm/lmtDIoP/67iJH6NJ00sePsHsUYW8n6LFkZRqzdCVvPeDFJMumZ' .
    'kvKLnmQrf/PEKHT+FlkUZEvV194Juso9aCHyKO1JTxGi31OvByvfU+I7EinZN/MRlkpXpomgfrvie2Ejcvwkj7tgO4XiPf7JDSqF/XtrShM5tJWzk8ysIhoL' .
    'svsSrzBTrN9t/hUdXfaMDtlEdpxGaidYWXvjPLP8QaRlHplkONgHRxcjr38QsYq9jPs6rVD/lxYiCmPtdLbxz188hi/KiuNPf3cpcEvrj7W96Ew5kUivcheT' .
    'G2s005E7s5a2lyHglG2fRvHxeBkPY8sm09DeLdi2VLYJM0R/bD7aetl3gelTafh9aeOz5ump7vEaVnj4viPx25k5Kxk8wV3PpQuCN/vhGGFCInxtaWH2c5Lu' .
    'PCS89z+xU5kHbwTrpQjwff0bOvwC9Tv2tmnVmsWnoyvVaaF86YB1RLuq4qIbiyO0L/6f1rJtTDG3C74X2Ryp0NKFo8035379TfuzY0pVcIX24xdkOoWs/2Sc' .
    'J8z276f/lhLEy9JHFvDRG5J6GX9yf9HoHZmPk147pf5BprtGu5mxtCB2skgfEp6OLkPkFJJ4Rvl956t3uTkB/Woa7fWnAcVpbV3ZaCZkxoNqL/u9m0/zxhxu' .
    '5144qe3PlXnMeavJIAYi21R3Fk42WszMDYjYdo3C2rLr0bBN9DTMUat/TtYW8WhLpm/TVnrKIv/3tWhicvRF7kStlSwhL8y21+KJ0ZNL8W8YCSrZWog8x83h' .
    'X7T0E+aHPJ+Q75CEeMAkRBt2ifM0PHtliAwCTDSvBtlqt4j2NRtx6DyHNuddCvEZ0nU+oBh4yhg7fxlUMabwlakYfBmgMp6n4Yxi0Bc7hscRizfJvxthw0f1' .
    'lmMyhryPsz8GLyZmDE+4vw8fLy25j6Mfv490/dF7jjQ2h8gdLFZ+YYekmM3XfJzCZG/ZKSJkXv0yCv123GDrwZ5ZGYqi9NAzoseo436E8ssIRt3Z2DwbOdS+' .
    '0rN9N/0rnxz9qEOR724lbjWa49Lcxwu2WT8zt5i/xFgYxTGei18kdMXdwNh7v6uGW0SHKVt93+kSs8yMkivqE9tOY04d2DvMYpzjSoXtJTBerEn7sfCdir7P' .
    'XDD/rz2t/JggHvlde52RsNuJdGjrRWZ56N7S9z/e7yWrj0P2ZtMkX+ZlMqhPUhLFa6blig1QxqNQvQtBGRQqN5IhwXdFnBEz4H7iJvFzSfw5NYmDJIlhu1jr' .
    'fTVGaprnrrzU/UYohq6Iovl/25US2rboeI+NBxk0rSJy/84oHzJ2TJAal0rGlLr+nZuvpc6hpXmO19yqbZ9aGoQXUPdcte9bKUmWvV7fN0nTBYNW5C/TuRQz' .
    'H2lRF5uvcq8aW5FVTFvRUqx/13ze5LDuICsnlHZttI/sJq99VLBZE8m6Uvoae3wz5hNbAda4h8ZItTU1smO+4/R/VZjm+YTUA9VOqLmKrhOCZ9uNIsEqbawi' .
    'GHyyWVUSJyb7LywXXPePTEwl5E+8+fEI0C2Gtru1xRtCeB/+xAzn1W9m6MDk42W594c1XzqLUJRe4nryRKFa3Fz/xucarbK3TLG9dlt1va9MZbhWJW+e5cd/' .
    '+1SGov6iyCcrPg3Gl0zmNCcNxv6axLo2o9/5zCIHKonNHG3bqFW3EbF0/pLkDhMHOw7Y2Jr1DNuYlycQuLS59NjEEeQoyeJekZwi4i08V0GlJsfbOJLExcIj' .
    'N/jbSh90dGDwkFg2f/GjXb967AcrnLBV7GLGgpc4bNeR4ei8PJKoC9OL73rLg2UddiXyJcp+xL1Sy9/e/Zij8iq2Q52Z4AdqyoHbkmXZ2/BGkdONNlQkwbiD' .
    'Vbcz0kXLkKGHBK+QF49hTwjGn9asr35Ot4pd+8x6WugTmxFR9Na37JL5VMFswiCimUn0Mdc6R17jvUvTY+6O+zroTajXGoWIHn/EnvrVMYUbS/3KE1nHbbji' .
    '4MIT+XT55SnX8iUHK2P51Zd7fSnUzlr1cVH0ucF467R7YlpJrU9WUjKdK+MyYpSphjwfeuhTFYgOCUsOXX53pcMQ2/mOxLUojvyW96cIov+8UQXdyHfD1Zyt' .
    'y0Mvb7SLGWayhhkj5qPFj1uFPTfzlzmiz6+nvm/N0z8vnLSk4jnxW6Fkcp9EP7ym9Ha3oLo4pxlmTlJpwP4P87WBjtF/CK2cufvzhi8Ucvyr75Ep6bsZfIrE' .
    'tTG4p6T9Frf6gfRJzaCaxP2PGvxLY2r3JTUkyCRndwVygwiHI4jeO1Ci5M3+uKaCxbWQo2aQJOPRUNO8wUMYSyZ5TZmAj/g+fiibfVj8Mgq71KYXadBfx+l9' .
    'Olsl4k5PM3v2kGQl5u1rPIbj32IpAfPsqsPZn4hoF16v/0I0xTOurHDpW8BCbK5Q9JxnW4qaE+O72bKhCxHnG++5YRNMEjefv9JlOSjsTeAhYMyLaKc4GeDR' .
    'XFutfTyd0KXFklH5+ODsndZPnsbtM2YU/va9gVqsUMQMVAoHys8CYjFFY5cMGdch3z1SKoRoMrbOCvAGHzgi+dYmv/ueykDzpCkZudErJZOiUeBDbmqmM/ce' .
    'mu2P7B0K+0Umgp4Fiq85O2j744jsjnphivsZRvfYH8Xc8qFxFJ4cGa99CYwVOH+sF36auNs8TxilKJJqtGLABLv9TLbDxxHxlVvxqUK7y0mSOBPezqNC9R+v' .
    'hB5R2wuvfj+KVGvMvDdjnl5dVvLM+T/nBpumntxYr0lUDi4D+teJ5RdfrjYsx4Y21KQQvckHrwonXU83osv7M0aOmL6mpLBG7gtwleroslDi2wZGYqDhoMVi' .
    'hLN5ISSmVKVwDl51lidrKAruCLDppHzVYeVg2xtuemxEeH9qC6dnf1tUXEPk9ZqH7lLHiSsW1zT78JOWqB72p4G/iLiGVaa4udlpt66pHgsNoabyJ54djblv' .
    'vFIwf8OfKkwiRNSLjKHgWCfdHIc2hj5fixr+wMj8gk+tJrEwybK+ykiHYbecQCErF9lK7+HYb5+S7n2qwFZ0lgLUU4qeQey/9d0iHqmjOA14LzpLqqK4t4P4' .
    'rbelHud8nlWZ6g8+/XBMfGLRUIt5svOTHl8nOTbeLKy6FDYcNh1OZxQR7hdV6tVRGrWnx9uJ8ge1kmtjkJSAcGmBqTlky4LF6qmm/Wuz35iF37BwXNxfh/Hh' .
    'zvh2/dHO39n9utd5/ABriZCQuKF5MJzacdYsWTwusuaD49r5h1oXJdhNupgEAW5LgHyvuIQ+ukScWBvRpIqfxtiaH/lkm9Vgr+Ya7otrzUHpsSHkSSsdjete' .
    '6tJyObIaVP/3bxypxWrQ7L+HOZJxeGSgCpmKLp89lJd9Ur0sup0T3vElfLmiY1GUv6OJ8fHJYkX4SUXem5/026JevfXN2R7jMf/xwWKlcVvYkRHQR22j1b6V' .
    '4MOk3XDJWhabjXe/H2eG32Rm5YS77d4qlM3dNH9bzGzOgf7qO/bfRbLYCCDUL6zWsPwczD8lbnES8JqQKV2qkKk1f/8lxzSrFd5EWu/LxpeVOZ1YtvHfnEq+' .
    'yVU6DUbQ70eglZhpVH5L+851Fv4yt1shdy/tLWPtDWbtXvj35Re5N2nlirnLGLWtq6q0cvxlwmi7eEHe7nPMS/melBJ7eWMteWe5Oo4TD8lnSDVtXWcf2c6S' .
    'jr3mJTJ8NKTNbsirM0sz9ue1kSs7EQ0v5wfDTNqMD7RlNAb3aaqoacpoXDM/0FbRcGYYZ9LQUK56+G7qbtrbbHpM7Og+tdxb2qw+O5WpyS+HmW20TYg10SqO' .
    'RWFlGOpxkbz9ldiEESFKkvqTRLEcAzNRaY8ktanZ9An+ArPi0QPFg4Aj5tgHvGpPshdWxRUHYRfqr3d82PufUkarf/CbjBOdUHtB09tIhZs64DsT63eFr5fm' .
    '94GgN49X3u8jDz0mHT0641uXJldFUfmPVTyM9LyM6Jg5LiZNtpvoC018IT9F27pKwvlMNzEWuvyKj9lDNrdgGCHHoqYSVhvNOfJ5A2YvNwLjugKKfJR+v01i' .
    'gk2Qyv9uSF1RjLASzGzCqF9DCme5v4ZU71cbLJqpIChctCbIMhvMUh/ux10vKY7VHnD+q7nVSUhGXLjtR10w+os6eflzrxD0tB/BBqxiMxUZNiEVbN8NQqgN' .
    '15Fpbpw/ZWTYfKL2DymefmI4X/vFirhTiWE44rEJQ9iaZ26R3bAg2ryS4Ee7JSy5hLVRGi0dZdLyXRyu4fcO2mOGDuRaPYZ/yMpnyBI4HbWVxwisq/3lI4hf' .
    'w7TcCV5HiFl/9ndHt1aKI7ZW5/+spQQTs6Omw+vJm0qocNqb8vJASV9cb/0RGLN1HLjVuvit78f6iUqn8JZH85VtQGf11ekF7pU32lbvqXtzHlP5aImfTXuL' .
    'RuiXRb56b3pvmcCLb9vxwx+M0wuc0hUs0o0Twp2mPrR9SsMS5KAeEcyYRCYp/cWaGEF1xrqDTL0eQkVCzVH7azVsNWWM7oEMebYlc/v8eFh7SuFYpwnzA7lC' .
    'ZpSFj2PjQUZvHvzOVJqKVOqQnMrMvp9uiho5OxukNCspm/7rfmS2tUUw1o+6jofBskjrf+uUmJS7Kf67ICfEFx6kwOkn/09xUFtrR+30vlC/ETGhl8fOHy/7' .
    '4X5tgcH7pBrE50anaju/0do38V/RlavRhWJz/d3s3GNr70fLf0YXho3iSPe3f5PGXfNU38vkp77JkKGCl8CJgsfQPfdzQ5MTQ00Fk3N9Aa8LZxWC5tDEuPaK' .
    'OpIAFW+si1xV5J3Pfm0b5hGipXjeM36oJu0BaEQycqg0Q+LzfsF5p37rEgS+1nEeSFctTS+Vdqp5lX3y3D5wCy0XuD6gtHggRJPKm7df8CjkVQ+36F/lrSr8' .
    'lUueo5XDI5yjBjX2qn5ei63LHp6tHt6jQ5ECtcsav4lW2SJVySK/hj7ZiVPV1OvWU1mfIo+GJtW1DskJiVzbzrKsp8FljSUIwcZyS1JhWw65WYFPcwPZgxvn' .
    'HOTGavkTPxPds32U7k5eQjRSy55YvVGrSX6vpaEqTubaVmAsDTXnunSRHVOh6c0lH94Dab2CgBNKcgN+HQvk6dQAvT9PmGiR2BnykRgKSB+yzz0RFMaiQSjl' .
    'ZA3kxBJk5aARvp4Yk0ALeF0ut5Hsx3XborfXotNJ2ez3OvVax/FRQGfLSkYbKZL/qwSp/BAL4ps/1MNJyD+ov1u8yiiQ1noo9uMPkiA21+yT5w4PFBRI33Jv' .
    'ZWPahi9kO5Fi+FFrlJ3KC14yFsZZek7tq519VV9WS2e2jC1UF7TUX963zBvod9KvZZ5pV6FLaeM2G99XocmRnkcxm8cdD5We4ZaZwV38iqw7z+XpICzPI/oX' .
    '3W+X65WLsOArb050z0Mu0TNHzod+PPLCJObm7zzjwle1qW9tcAxUt5XxbrUfT9sYbLMFKFNPa6vSUyS4P2nqqavASVgUauLX1a8g2GWdC2hdbx7QR6R1OMj/' .
    'kxWKdMSR0+e3Tp7lKSrAanqsf/6nv/Rc7dv6zp97pgdV2AYmtTIjH0N/Oz8XnHb9suw+5p0qT1vfxW9nrJe8XMZlXqZp8N+8JtmSg4lBWbkJZ+47x2mH/wp9' .
    '9Bvpn1ZPsHJbcxvnnEdnCX1aVzHj5qbAuU9IoHOAoP7k/jgCOSHO3nrZ9sjvuM6Rgd3yzsjtdb4XznnYT+xYsO2euLE4M6alV5ub6YqNX1KkLE35+Oe4p+p5' .
    'IiQ9NCkgNanVK3gVSIkQgq+ujL3DjVOK3+KETSCtVJp8qpuwxJeSS/7LLcFjx+RBnJg8+kAFOkHcvDPM/wFbv6t1U6ncbFPnkU2mPataIW4doWQjCaE1pfkk' .
    'st3QJCctQweOnSH+JYXhYYQh5YIj8dZMvOz9Up4vlO40VVF6qLsim8xbve5vXshoN6VXZ81Hb0qTdDLQj+Sy0dF3tqmcxxQXK83MmTO7B+QSCs03Uq5sjeDY' .
    'UNVXWEVhfsa2MJ0eaX9PrGpD6o8+0as+4Jk3eK/qIj8HVjp4KOK0moh3fcFRBRvMSc/PR68aLM25SIc9rEq/yCkdbOcIoCN3EFlICwisxguk8+P3C6SjCryN' .
    'ifRRfLHV8YqQHXtB0Nced/oFYferyA4f261XitjxspM+r2y7fSZlCSMFDUyj2e2xr5x/eP/cfxYT4Yu7wG6wI4gdb9R8HWDTIVryGo8WRhWody0qLku4OXsb' .
    'ICseL7p5PdsR0DzrtylKeJjmFiC9W06jR4sH26BiD0RHwCuZoMp6rWsTbbGUQyqb0/cc1a46oMdCNpp0nN5maYkUV7cjx8JmgLqCL73bsxu1Z+SWvlrVTjn4' .
    '2VK3Qa3W9u0IvTL/G9WuZ/tPAucVy+LlFviIFR2vcWZpkI63vqsFKu7Ll81XPAvu/yAWZWvkxudnukfYLZdwzWeaINdN6EjsuEDo1/1NTlDYSGTtqYj4eCNb' .
    '6R8rxnoRcSOR2qfCVlYiRoLNT0WERayMhBueigty1LPlja81aguXFv9pXNNl1M4r1q23Km0k9WF5Es/6zmR0dLdi5qtnX4UJC1ESqw8hIRFL0jzrEx9v8Xel' .
    'lKSCDU/6ds9Gv47OKJnid4zAKv0Wusbs9nff2vNSPck+r6e9lHq3fLumdl/6gU9FVpVwmtc5bQXvpfCDtCyvJ1TZwpdVAW0v7/9Qe7eWg3+cPTJ9qmuV+VKq' .
    'rT/gHeGP2Mv/NvXQJGTwFIhWvdd9wmL1CG1+jI5O4BOibfr8mBjF/+FjgxavYB1zIWEpQ2StgEcks9ri/c47RsLaUkEG1edpvKOr+mDHzxHEB7G36oQaTwdQ' .
    'XS8dHdUbUTVcCS8HHJ/6ELoOogYNjATIxipks8W89+DpTSA5TXxPzKaCV4kmfPVXU0hoLDEgZMk53N/1lY5vHZpQ/ZCm0BWaTt2r+jpN3/pXQmNo5q4h/iTh' .
    'twexB4do+LxvUMPeuKDiVznHznEUpDR8fgz9gdRvkcMZ3KcwKXg897m0oeExk/H855TSLyIFpSmPTOZanPQHmaKS5JwkpjpJo5gG5TSmCpxwWpI6hkPeINJM' .
    'bOIVbtGNkPgNvVqarzncweBHnAjpsPnwZnhKUII6RbGGmW7I9jqGhHlk6KPt88JEPL/n11t4Q4l0zAUizfwqS/zx4zdRdue7x/dkj8IRjm2mGHr5m5kIl6pF' .
    'AnMx9DtsXI+306Pcxnf9zxVVTL7oXY6Gnx/jjKfvbvuHc6uVRbeqSjkKfkNnMUjS4pTqVw1v/YobraqG8UOy7Gsfbj93maRUOEyLj9TRQLBoGJ2PRdDAMYmF' .
    'lG9PaxpdMOUdd8kRJ/19sqSIkGpRaVGUSJSh3y5Jyq453BSZnCXvhnpQSENdIp8hN2FJvxdNqm4KieBPEiWT5m/DImtqQk6a1wnPwlVKlshqYqI/2JkuzpLA' .
    'IDf5NRaNS44xL/EraywZN3yM9peESU5xwXTWjqgzWw7TQdNO1vTBdEFWsX2OKMmR/Ae0ae3Lmpa8hrgD+y26t69cWG/SjsL+dJH4GNAcHR79TaPzx2QV2crb' .
    'qTloidtqyItrOaixj9vJE9g6aGjplXIWfmKtsBQehSWcF9ByKWzu/FNlXeqJijba7xRz71+J03bWKScKm/WXWC3htziMQ3S7KGdBPt0oiruXQ0F0Zx+eXIbs' .
    'Rp6o96yuU655ZOmGqF+6f4is2N119/kwEBlSceJwWRESqf4hddyatufUcm081Xpt1UM5yyrLumf8NNVSl8Xuj1M+B7+xlx4iSnNUpzb/NofuwyKnQA/rB28v' .
    'JuxLnexYtB/yjwfJTUQZi3uhyCHqoXg1z0WF4kzMyYkjejm6kggjGBhrEsV5Y5/aUEuhyCmzKel+f4VgTOKoaSDsWvxKWQxFV06plA9b5tKwQ8+2tAetlue2' .
    'IqxC+XaLh6O2gA09VMi391fUCOelyU1QZagSei/TVbGQkAqsQMk3tLhXCMaGcvWL6bKyLAjnZsSE57Js/vlNVNB8UFkUj//lCK1atmNf9c8l6bi4R0Tm49J7' .
    '5tk/s/jV+voUsrOWqh3VFFQf9O9VL2WhOJKZNL4qmr0UzDHajXU8IRonaJNeekTw68gIb2/F1Lt8KV1YBtaCiXcxa/prxdVxb8FI6cIixtV0b9Y1xsL7V/3b' .
    'dAkumHn72/p77ebo5S3tLffKMWH15jUvH8xqfb8NLha8GaOozZh8ScnU4eJtVz4ckF2DJDa7LMvFtP3SO9WFtbOTcZ+OsH9S5yZFsLY4I4X6pvhF7Vjti+7t' .
    '0uMnsWIZl0OcYvve9hKYyX+LHGvX3WLtJr9XcHT/tSavbXF8W/SsWBwTdc1Q5iDr9fBMscAPrR8bNQfFWYZcFE/p6UqXEfPZO+daao1MxVw0h9Pbzcw+vnxa' .
    'jshBT6FlNmT2XebwnrFpp1F+bUmL2mm1p6ynbWWLkdzDhdq5Ep7KPYRHz1qUP2XPmUaTTw1zcXXVnF7JbD9qcaxU/o3AI2DX1V7uW366MGw89Sn5QTT55MsN' .
    '9WUF3tdVywrkLyfVdTLXh7wNoxspDGgDl8jowvDo6Fr/4l1LeUevjz2d0cxslaLzi8H7+AoBjfZjCtm0Obc8Z+Im0+50ogHn7lemLhusWY9RtfH07eEnnVXo' .
    'k3nfLF7wbAlbUVZifwv/7C1gJ77ANN7AEPnUQPWeM0OwJyv9KXf9CmnDkx9GYnIRlJP192s/vX3MnDH6qEheR0ImCpb+cpCC+Dl5z49rvIr07I/7Cjw9E58o' .
    'R3ldW+6NwVii5GXUtm7kGJxbvA5odHSS6pu7Nk6RnE4qyZTFG8jdFdfGaGgayMfcxdcUFRvIoSXu7sv1ziXcTjopieudtIuvXXg41zto+bq4cL2DVpJ08qWC' .
    'mkh278TEpUKvWnK2iMilArSS1dQuFaA10YuS6EXFa7vl7p7otUWFYsvLm+gFLRQqqkQvaLlvKXzl9qShUbpBPY+DZc9pamqex2nCUOeys8/joIUKo7edI+Gj' .
    '/C3jelMi7WUa9fHjTUmUtKupl9dNCbRcpW+tbyT/ZmP8+GF9gyF5m/33r/UNtG4lR99Vl6fJ4A/WoKucDx1MHFfHVcdXR2nR0sZVa0G/qYY2tKrjHWDHRHvI' .
    'zcfHsONmIgfkvT3YMbQciIhgx9A6bh6No354Yf6ivDyO+sXDUfOLizhqaI0+fBhHDa3yF1wqPHS3Ns2EhCo8zXRcNre3KjzQ4qKjU+GBFmHzcO939UtzNEGM' .
    'wGimstrpjf58mpY9Gyla2nwaqZZ+m71NGSJihoeKLi4yRIrEmw8ZMrTpUa3FxhkYtOnHUTPErDtmHuH9dBBLTJx5JIbX4fDz58wjaHXg4c08glaimJjmtuvo' .
    'XODCguZ2oKvY3Oio5ja0xFxdNbehtRDYN9ev4vE24/p6rj9Dpe+th8dcP7T6VFTm+qF1nZEc3zYGyx/39Y1vGx9LzofB4tuglTw2Ft8GLd9xpkShF+UCyOTk' .
    'iULIL5gEyssThaDF9CJYujSkXCCspdKXPc9pJ1tc3Jc9O69yx8nJlx1alXl5vuzQEs9GwUsQJENyQELCS3AQREEiI8NLgBaKoCBeArSQHDrDnY56qmvw8cOd' .
    'ao46q3sEZboQaxFU37yR6VJFFESopWuilesoOs/MbKI9l6Mr6uhoooUWndzg659fbTRF/KccDjLujWq4ujocaGRMjd6753AAramMDIcDaLlqeHsUN9wIx62u' .
    'ehTHNXgL39x4FEPLu6HBoxhaq3Gsy9IYDs1Y4eHL0lgYrM0OkYXPBr4FZwd+ksb41MwbLrrc0+Mp9Tg7OLinJ9tz+bGUVE8PtJY9te1UEbTJd3frF/uSMGvq' .
    'mpoW++qS6mswMRf7oFWflLTYB62muu/xJ+8rGAzPzuJPDN9/Z6ioiD+B1vf37+NPoHVmODu2/+b1S2QJibF95DezL1+b1araR/4U7uysVRW2N/sZqeS2ULTX' .
    'ZIGO7rZgUaTUtLfntgAtpaIitwVooVuYVJWVEgsynZ1VlTGVmggSE1eVQcuktLSqDFpnTLw6SrcI0Ti5uTpKOLe80QgIOkrQ4r291VGCVi6Onqf6onmY08WF' .
    'p7rTol6YubmnOrT0Fhc91aF14RTMKDbTH41dXs4ohj0THN3fzygGreCZGUYxaJVjP3s+kDRC6icq+nzAL+kZ6cjcsgm3NP97cvJlk/fcc/zS+oHkvL99Kx4V' .
    'qhXWBeCXGBmpFZbUFeIHBKgVQquwLqOjmvVJqDsFRUe1O2tG6BMb5udXTJJUSkrMz6mubCSZkrgvWoQ3SRFYv/gzF1c0d3Z+8W9mZq0oLv7iDy1W5rY34fr2' .
    'pBSjShJi3Nby5u7uEmLm3Ery1tYSYtBS4p5aKbOLcuafm1sp47ebco6KWimD1pSd3UoZtOb4azzqYIn2TOuZfWIV6/EwLKw+MVhFZvz6ep8YtDIraJDp3Xbf' .
    'nM3NIdOfudG82d1FpocWjZsbMj205s620/y95ocF7O3T/AW8tofn59P8obXt5ZXmDy17gc/XN2nEeW2jo9c3bWmf84gPE7rxxFi43r5N6ObCO2QR+683PXRj' .
    'LjogoDc9OvS/uY2ZKnccu6yei4sq9x6cmSy7DwZG53avnyKLG5uap9wcJCQYmx6Yi9+kpBibQkvc3BsDN1qN+bW1NQbu62hvZrV3jT5s6CfVHh6NPtVs707Q' .
    '646xJtqTZxARj7FmJuqS29uPsaBVNzFxjAUtxJlDBu8978ByNzcG7/K9w0Bvb4Z/63Bvj8EbWm7lsNCHy17of5eXQx/+XYaheyGjJDnHdV0/f46SdO2M3BU3' .
    'Lo8wm9389eREHuHr7HhzdrY8ArTGZ2flEaB18lVQoLoi32FlcVGgeqVC0CE/X6AaWoIVFQLV0FpciUthPMEa0KyoVXCfVx0v2NhQcC+Yrx1XzWt2/aSuV1qC' .
    '0vMt58cP835YvfZj7xwWFpZ6bZbHsBzvn8HC6NG03FLDcfEnQi2Yj/sLmXdlNssyMgqZy3b7N2XaaJw7/4itdinrk89tZbr8+aNP7jKnnLm1pU8OLeW5OX1y' .
    'aP1x4ZUloOFVWEtKkiVYg37DC21o8dLQyBJAK2lt1dPFE5uLDBPT04XMc5ULG9vTBVqrnp6eLtDCJDuy4ty9PuVUULDi5Nw9Or2+tuKE1tHurhUntBQ4nwoY' .
    'x0W1+v7+LWDsG/e0NepxX/99jlQhclMY8w4yF72QqZQmCb9pn62tlGYfiakpP7+UJrRMScq035AbzT6EnSD4htVTNpn70m5h/7Es4/9JRSoeNVMLi+p3JsdE' .
    '6EotP8KWCqHaapRlOuerQYvg80v+ecCiq6yomPxT+cBPl8WetWDHJ+6hLFojD6nv4yX0xuIpXgwhfQSSX/V2SDc21gxCvF1jYbqYPqbJof7gn/yzOw3JHPnK' .
    'IAQb53/ejc7QDX0V4kVnmICWAAzDJwi6Mk+u4iSwFLdpzfNP7SqVbJEzl48duXKlrE9oiiWZzPA7r6pMLZRs67SXl0iVh75CN6ld0PooKR3772rmqir2qIoY' .
    'uqzrF04k78RQWsX3orh4/FA7Dp/VTXeP5lHSiYpGwldlxh/9VNBXgcTV/l+CMuTv0Tfwz6ErR4q0eyFjg9nLsSTW96x/Cx6bYq/EEhzRvuDIWKGNoLuifZ45' .
    'kMj5OMswwAd8vWeNbS1Cav3b6hLRGrtY8YjA7vEK7fP70GVWd7a2mWgBPrbuLds+P4JxgK74nv4tE2JAt0aOeAGqDW63KfS1WBupmxtahjn4urfQ1S2bky4n' .
    '4r9L93Grg4jfX2IQeA+xkSpPaAd5K0/uISIfzG1hfxO3COSZmXyActWIdqsxiYjTzHS0b8CLDF3tYw/xIh80Q5fDXxaX1K/ClCcY43m/Gj15Iv9QM24lRPSH' .
    '3pfFwKsVab3pL5rQ1/WlgS8H0NoKnH4YbNiynsCvycjNrfmOt0b1umdiOcNz7PYPnsLqoR0Nx58bXIodacvH19OuyT8ndq+ut6Cv/RNH1xnQmnY9/bMDXeEp' .
    'MP9RtbyGLhlSeT6+ckb2kRSK8vPT8/5JLmQQ0evh5UeRmovqw+NoKrUsjOFjjsEumOoCrRzUZ0K+0BXMj0bI108XuqTkOg+TpjN5MN9FpCS8ef+0rWvx/gXP' .
    'M6ourrfmD/aYJOa5FKGve2FLXKzQCjRf6HoCXREr/eqSolqFLn9fxjugBL/YmqDweOZg+/sq0JU6EHv+ebj0penzqLRdzKEw6gamb0vkXy6DoGX2fNp1iyQQ' .
    'OVBfgUK+39bn0iSqBquuuHApwJ+JtqPOrknylMmBRramt26/pn6zDNmr1KPmM/QVr86n5jO0ajYDmJqhK/KOc6b+OlPo8rqHOkJ+lp7xp1heYNzBZZhCPYoh' .
    'GwVWrWdPFPMI0SOFvhUUdbf9G6M/PdPQimFuD427eBYyniAsFrp3UhyYImU992pdhD6SdidD/5NP+gDbjm/6VLF+Kp21A6vI0Jvde9a70Ne5V5TW4tCyYb23' .
    'UwJdpeuz7hikOkKXbOT2YZ9HsAPUacTV11QK0Fw3l6vDS8zZw8hjsOZs3D8+Jy+FvpqEvSCfhVYolvFm3hJTWKNVFI1xkRw/wrJffvue2jAGl/fl60WsMJ4g' .
    'tcsI82D8FWHJ/CP8gZ9cSi75MtDXX3sB+SPQOsR3vPx35bCodLkhHARdyi1WDjweP8N5hk7KnPlKsCAW/RVFYdZDsbDF4evpWgQ2hUUG6GvDgMriMLTGr5XR' .
    'k6ArWuYY9IdiFtDlG9e0y9OWDbcL1BmduueSM9J4ZDwvzb32VTwlK3ugv7BRXS+gr9CN6680n4u91WM8C8pDOx5XSVRDRcPBsUqZDY+KR5c2GUO2Nsk/FFlC' .
    'NKQ6HIjysqvcc/FLKo0Q1Sk3mKGvzhWTG6c+7+gbXk9L5bc2k73McbVNp5e2grXq3bwern7cdWa3TJzgzmtRiLLMQ5brmmiBfjPZyWJ52GR3U//v67DFzSNo' .
    'zXRaLbtAVyQJaOG1f/8LMhU1oAs2HtM4uxHdYki/71U0v77lwrJJmVo6T6d5ahR+O8NNNwR9jTYWoNOElsap2BYxdMWavpPso7Bu8c7fZ1e85JOSsOnMukfC' .
    'mBjuTsG6gN/SaCZ66W6ZkKSw7ZfJVJwlrtjFBMHUrfkQpARB8fV/V+4JhevJ6GLQZSkpf9g6p/j5YeOEgtXxl5sxm66Bk+6SOZW/SXMFnTwD3aQr0FeesHNS' .
    'JvGTpVihc5uunoHriQK1RsWim5kzyz9lAx8++ChSqw98HC3yOEgMa6hxNnHwYe4ui1PxnaCJ0y+Lg74OfDAsc4RWuopBg2UDvXWAY9fAwJlrzvsCmK6mqr9n' .
    'nLxqDjq2OH6RjkAOOoa+AH6ZgK5Upoe6qr+C+gSngCOOoqw6K7rXtBqfRI4AdAXd5qCX/bsUN7fhiDz875E/CsFm9PW91wEoe/dsYrdpvM3Z9C8sOGJczP99' .
    'tefwMb+EFoO+N0ogdEW76YcyT3MBXfrp/8lhjgh2LnqJvhNq9zkm8qUlVkzkdl6MAdsj9qcnyi1FLgNnhAyh7PpvhpxZPsNyniVjJf39pXShaFaG8Pgh9ls3' .
    '7tPe5W6jJu8D1aqbX+e+3gcXN42q7V5u+707Qjq9VW6t0FfR0ya3BWgd9X5/YGmw7eL/dJrSOgs5Y+AJroBlkAdeZVwgStCsZIiMlh5KUKiR4rCklgCsBsE8' .
    '3jFG4N9XkyCYAPq/VROI8u/q7awGyqBkCHSpddiB3k3cU+t7cnCgGjAXG3rifBssczsbe4jaTdFT0+PiuSiGwPCO2P1qa+Fdqsvg4okUdHV0EHNyMBsAXca2' .
    'flf3O3nddsr4V5mQzKKNiZF0pYdMzpShxbIofVDEAp/dIx7BMaP7TGO/bTzaJ7xE23Phr6Hz2QtGWVNi6JJJRKt17Im/Scs7Yxebj7paL9+yxwZ3JI54mG18' .
    'R9fTXH5fMsU03/xeLrteJSSuErWl4W0P4xzszTvXZjreotY+7GcA8xDqAf7F7/BP00AOcA8hH8SBjVMkEAMUG8hBDPC9iwFJXO8A5iHUA/xP3OFf5FIB4B5C' .
    'PogDyXcxQO1SAcQAlLsY4J7oBTAPoR7gH/UO/5rncQD3EPJBHFD4yg1iQPZ5HIgB9LZzIAa43pQAzEOoB/j/cYf/v9Y3APcQ8kEcuLW+ATFg9F01iAE16Cog' .
    'BkDfAeYh1AP8H9/hfw92DHAPIR/EAYe7GEAEOwYxYPQuBpTHUQPMQ6gH+Ce8w/+tCg/APYR8EAe47mIAnQoPiAHDvd9BDMAIjAaYh1AP8O8iQwTwn6FND3AP' .
    'IR/EgU0ZIhADGLTpQQzouIsBiTOPAOYh1AP8L9zhf1RzG+AeQj6IA2J3McBVcxvEgL67GHA91w8wD6Ee4N/3Dv+w+DaAewj5IA4k38WAsfg2EAOY7mIAeaIQ' .
    'wDyEeoB/8Tv8O/myA9xDyAdxoPIuBuT5soMYgHIXA5DwEgDmIdQD/OOHOwH8C8p0AdxDyAdxoDPcCcSANzJdIAbQ3cWAzCZagHkI9QD/rnf4v+dwAHAPIR/E' .
    'gam7GJDhcABigPddDFj1KAaYh1AP8B++LA3wH1n4DOAeQj6IA6zL0iAGfJLGADFg+S4GBPf0AMxDqAf4b7rDP+ZiH8A9hHwQB+rvYkDSYh+IAd/vYsBZ/AnA' .
    'PIR6gH+JsX2Af7NaVYB7CPkgDsyO7YMY0FmrCmKA0l0MQHdbAJiHUA/wf3aHf+KqMoB7CPkgDpjcxYDSqjIQA3jvYkCujhLAPIR6gP+LO/ybe6oD3EPIB3FA' .
    '7y4GLHqqgxgQfBcDyhnFAOYh1AP8iz4fAPifWzYBuIeQD+LAs+cDIAaQL5uAGKAfSA5iQKFaIcA8hHqAf4qOaoB/G+bnAPcQ8kEcyOioBjFAifk5iAFJ3Bcg' .
    'BrB+8QeYh1AP8K90h393CTGAewj5IA60vQkHMcBaQgzEgKm7GDC3UgYwD6Ee4D/zDv9YfWIA9xDyQRyo8agDMWC9TwzEAJq7GDCHTA8wD6Ee4N/+Dv/zaf4A' .
    '9xDyQRzYvosBXmn+IAZ8vosBo9c3APMQ6gH+A3rTAf5nqtwB7iHkgzjwX286iAEXVe4gBnwwMAIxQNzYFGAeQj3AvzUGLsD/u0YfgHsI+SAOeGPgghjg0egD' .
    'YkDdXQxAPMYCmIdQD/Dvdod/bwZvgHsI+SAOHN7FgD0GbxADYHcxYDn0IcA8hHqA/5M7/GfLIwDcQ8gHcWD8LgbMyiOAGCB4FwMWBaoB5iHUA/zX3uF/Q8Ed' .
    '4B5CPogDcSmMIAbkNbuCGIDS8w3EAFi9NsA8hHqA//47/GcUMgPcQ8gHcWA4Lh7EgDYaZxADlO9iwB99coB5CPUA/0l3+OeVJQC4h5AP4gDvXQygkSUAMWD1' .
    'LgZgeroAzEOoB/hXuMP/tRUnHPcwZhAHju5iwK4VJ4gBT+9iwG8BY4B5CPUA/7Z3+OeX0gS4h5AP4oAptP/FgDLtNyAGnCD4ghjgS7sFMA+hHuBflukc4N8v' .
    '+SfAPYR8EAfKj7BBDFBM/gligD1rAYgBaI08APMQ6uH4N00G+PdxsgO4h5AP4gCDEC88BgjB4DGgewzEAIYJfjjmXSnh+B+5AviPJZkEuIeQD+JAalcpPAYU' .
    'SsJjgHwLiAGpXZ0A8xDq4fj3ogD4x2d1A7iHkA/iQL9wIogBJyoa8BhA1QliQP8vQYB5CPVw/McSAPyv0EYA3EPIB3HA+p41iAEDiZzwGPBbEB4DREjhmL/l' .
    'h+P/lg3gX1d8D+AeQj6IA93Z2vAYoJEDjwGmoiAGdHMX3GG+Eo7/Q2yAf97KE4B7CPkgDoxbHYAYsIX9DR4DHqCAGDCJiAMwD6Ee4J8xnhfg/6FmHMA9hHwQ' .
    'B74sLsFjwGIgPAZoXoEY8OVgBY75nUM4/vEUAP7/3OAC3EPIB3HgumcCHgOmXeExYCsDxIDrjJ93mNeD4z/KD+BfyCAC4B5CPogDqTwfQQz4FwX+xYBlYQwQ' .
    'A1JdeOCYf7IJxz+REsB/1+J9gHsI+SAOcJ2HwWPAW3N4DFCkAzGAi3UPYB5CPcA/hcczgH9X6kCAewj5IA5cxjuAGHBp+hzEgDDqBhADLoPS4JhvtoPjn7YD' .
    '4J/JgQbgHkI+iAM1WHXwGFC/eRcDCkEMqPmMDDAPoR7gXywvEOC/HsUQ4B5CPogDPdQRIAb0RDGDGLCCog5iQM80ERzzJT5w/GfoA/zv+KYD3EPIB3HAeu4V' .
    'PAY4sMJjwK4IiAHW4kMA8xDqAf5pxNUB/jeXqwHuIeSDOEBuHwaPATFY8BhQOgJiAPmsDRzzWGFw/L9eBPi/jDAHuIeQD+JAfvsePAYc4cNjgMwwiAH5Iz/h' .
    'mE96Bcc/KTPAP/orCoB7CPkgDixWDsBjwPA1PAYwjIMYsDhcCzAPoR7gH3VGB+Afj4wH4B5CPogDrmmXIAZ4SlbCY8BFC4gBrr/SAOYh1AP829okA/xLdTgA' .
    '3EPIB3Fgw6MCxIBc/BJ4DGC+BDFg49QHYB5CPRz/xAkA/8s8ZAD3EPJBHLh5PQyPAZOd8BhQ/xjEgJtHlgDzEOrh+GdIB/jfcmEBuIeQD+IAXbAxPAZonsJj' .
    'wJAGiAF0muFwzI+JwfHvkQDwvy7gB3APIR/EgV3xEhADdsuE4DEAZwnEgNSteYB5CPUA/40TCgD/Nl0DAPcQ8kEcIOUPAzHgb9IcPAascIIYQMokDjAPoR7g' .
    'f+DjKMB/Q40zwD2EfBAHygY+3MUAFXgMiPMBMaDMcQKOeQH8O/xjA/znoGMA3EPIB3FAV1MVxABdqUx4DJjgBDFAnRUdjvnAazj+CTYB/lH27gHcQ8gHccDc' .
    'hgMeA9j04TEg8hDEAPNLC4B5CPVw/KPvAPy/tMQCuIeQD+KA/p8cEAMM2B6BGFDkMgBigP6bIYB5CPV3+FcF+Pc+uAC4h5AP4oAb9yk8Buz3wmNA6zKIAW4L' .
    'QnDMS4bc4X8W4B8lKBTgHkI+iAMClkHwGACrgccADzwQAwTQzeGYlwqA4//gAOD/xPkW4B5CPogDhx3oIAYconaDGOC5KAZiwNUWHPMQ6uH4/6sM8M9IugJw' .
    'DyEfxIHW7+ogBrRYFoEYwO4RD2KAxn4bwDyEeoD/d8YuAP9v2WMB7iHkgzggotUKYoDZxncQA0qmmEAMqFcJAZiHUA/w7664BvA/5i4OcA8hH8SBf+//0vAX' .
    'fxADnE4qQQxYG6MBmIdQD/Dfq5YM8A+RH+AeQj6IA//e/7fgL/4gBqiJZIMYkJwtAjAPoR7gH5Y9B/CvCUMFuIeQD+JAlLQriAEQ+UEM8KShATFgTlMTYB5C' .
    'PcA/huQtwD9EfoB7CPkgDmjFV4MYAJEfxADJv9kgBpSnyQDMQ6gH+G8mcgD4h8gPcA8hH8SBf+//L+Av/iAGEO0hgxjggLwHMA+hHuC/mY4L4B8iP8A9hHwQ' .
    'B1r2bEAMkGrpBzGA7tYGxAAum1uAeQj1AP+KxJvjdz8BAHAPIR/EgX/v/2LwF38QA4gZHoIYMI6aATAPoR7gP9BVDOAfIj/APYR8EAf+vf9nwF/8QQxwHZ0D' .
    'MUBsbhRgHkI9wP/4WDLAP0R+gHsI+SAOQOQHMSCkXADEgDFYPogByfkwgHkI9QD/2XmVAP8Q+QHuIeSDOPDv/d8B/uIPYkCe0w6IAZU7TgDzEOoB/muOOgH+' .
    'EWsRAO4h5IM4AJEfxICvNpogBhz1VIMYoIooCDAPoR7gXyNjCuAfIj/APYR8EAf+vf/HwV/8QQzIuDcKYsDU6D2AeQj1AP9YGKwA/wPfggHuIeSDOACRH8QA' .
    'BG1yEAMwHJpBDPjUzAswD6Ee4L8uqR7gHyI/wD2EfBAH/r3/G8Jf/EEMSMKsATGgvgYTYB5CPcA/8ptZgH/7yJ8A9xDyQRz49/5vAX/xBzHgzeuXIAYI25sB' .
    'zEOoB/hnKjUB+IfID3APIR/EgX/v/zjwF38QA0qJBUEMMBEkBpiHUA/w77SoB/APkR/gHkI+iAP/3v+x4S/+IAYsmoeBGKAXZg4wD6Ee4N8v6RnAP7c0P8A9' .
    'hHwQB0rqCkEMgMgPYkDSCCmIAe+55wDmIdQD/LuzZgD8XzFJAtxD/88A4kAzMyuIARD5QQxgfRIKYgDVlQ3APIR6gH9ua3mAf3NuJYB7CPkgDvx7/+eHv/iD' .
    'GKBvTwpigLy5O8A8hHqA/4r1eIB/WEUmwD2EfBAH/r3/n8Ff/EEMgCXagxgQD8MCmIdQD/Av4LUN8A+RH+AeQj6IA3hiLCAGcOEdghjgNT8MYsD28DzAPIR6' .
    'gP/o0P8A/nHssgDuIeSDOHBgLg5iAER+EANCN+ZADOjBmQGYh1AP8P862hvgnw39BOAeQj6IA//e/2fgL/4gBkSrMYMYUM32DmAeQj3Af/neIcA/RH6Ae+gj' .
    'iAPOcV0gBlw7I4MYsOcdCGLAYaA3wDyEeoD/r7PjAP8Q+QHuIeSDOPDv/X8F/uIPYsBsdjOIAePN2QDzEOoB/udVxwH+C+ZrAe4h5IM4wPIYBmIAejQtiAEn' .
    'WAMgBnxS1wOYh1AP8L8rswnwX7bbD3APIR/EgX/v/y7wF38QA06EWkAM6PwjBjAPoR7gf42GF+AfIj/APYR8EAf+vf+TwV/8QQyg4VUAMYBXgRdgHkI9wD/n' .
    '7hHAP0R+gHsI+SAO3OdIBTFgB5kLxIDd61MQA45OrwHmIdQD/P+LACTwnwAAuIeQD+KAeNQMiAHkmAggBpDwm4IY8C8KyMJf+AH++WrQAP4PWHQB7iHkgzjA' .
    'iyEEYoAd0g2IAVIhVCAGKB/48d698AP8h/rPAPyfhmQC3EPIB3FgZt8cxABxm1YQA7rGwkAMGOd/DjAPoR7g35WyHuA/w+8c4B5CPogD9QkzIAYQT2aAGCDZ' .
    'IgdiQFunPcA8hHqA/4vHDwH+dfdoAO4h5IM48FDbEcSAwexlEAPIOzFADEj4qgwwD6Ee4P+I9gXAP90VLcA9hHwQBxSPCEAMuB9BB2IA9F+AGPA4yxBgHkI9' .
    'wP8+PwLi3U8AANxDyAdxAMH4FsQA6AuIAWaiBSAGiBegAsxDqAf4R6o8Afi/h4gMcA8hH8SBE9r9/+u0F56syzgO4zYomk1ZeaI5xDylleWC5akwUytymZUl' .
    'ZjENowjIVqQiKYoH1A6YHYzQMi3BA6NWkzKaVkuhMDErNStaIoUotqgnJ4Ldfe/rYffu7f8Cfi/g+v4+GgN2hXprDFj1dZnGgDFpixTzJuoV/++nXK/4b1hy' .
    'k+LeRL7Ggd2NL2sMuGdNgsaAyeeWaww41zBOMW+iXvH/e0uW4j+meZzi3kS+xoGs2K4aA9q6xGgMqF83T2PA2qojinkT9Yr/BdPmK/73zc1R3JvI1zgwv6pA' .
    'Y0Dyqn0aAx55KsKOAfFPKuZN1Cv+RzX1UfyfjZ+ouDeRr3Ggz7/dNAb83uesxoBxfWdoDLjiz0GKeRP1iv/ZmV8r/i/5dYri3kS+xoFFEYs0BmTmtmoMiMx/' .
    'QGPA82+cVsybqFf8f5z1qeJ/QsU+xb2JfI0Dn47tpTFgZuwEjQHbSo5pDCiPyFHMm6hX/K/+q1Xxf3VMZ8W9iXyNAxOXHNYYENq2SGPAbb/00xjw3WVXKeZN' .
    '1Cv+t+QWK/6PbpuuuDeRr3GguLZYY8CTxUc1BjSO7qcxYPS3yxTzJuoV/3/cuVnxv2J7quLeRL7GgUHLKzUG3HpDJ40BW7+7RGNAXcYcxbyJesV/5+Xxiv/8' .
    '6AbFvYl8jQPxi2drDFicmq8x4K6DF2sMqK0appg3Ua/4f/OREYr/krcGKu5N5GscGLE5TmNAWkyJxoChh89oDPjpo06KeRP1iv+Pp4xV/M9KzVHcm8jXONCS' .
    'Fa8x4KEDhzQG/Lv7hMaA/0eBH+2HX/H/edJgxf9l77ytuDeRr3FgV89ZGgPGPVagMeCq1gyNAR+kXKCYN1Gv+J+TkKb435T9iuLeRL7GgbSS7hoD7l88U2PA' .
    'jqF7NQYMfrRFMW+iXvHfJ6dU8d90eZHi3kS+xoHSX4doDGhMW6Mx4NDdZzQGpKw4r5g3Ua/4P5TYRfF/7Ic3Ffcm8jUOdGmeozEgccExjQFb7hilMWDsqEzF' .
    'vIl6xf9j/5Qp/kPV20fy8dc4UNt2RGNA+89nNAY0XjdGY8DmPfGKeRP1iv/SuX8p/mfMzlXcm8jXONAvPU9jQPbG1zQGrM9N0hjw7JFYxbyJesX/mOjScgSA' .
    '4t5EvsaB0qlRw/n4awxYOG+1xoC5kycp5k3UK/5faOut+M8oPKW4N5GvcaD343GFfPw1BpgLjQFn065VzJuoV/wvzdqq+H/xuVOKexP5GgdePf6VxoBOQwdq' .
    'DLhyVb7GgGtuDCnmTdQr/j9s/0rx3145SXFvIl/jwKmnF2oMiFhXqzFgX321xoDmkVMV8ybqFf9jl4xX/KckHVTcm8jXODD+3pUaA5YsTdEYYC40BnRKfUkx' .
    'b6Je8T8pr07xnz/+vOLeRL7GgbrCvzUG5J3P1xhQ3a1GY0BMTYVi3kS94v/SnmmK/5qetyruTeRrHDj+0FMaA7o11GgMWBB6XGNA8YHRinkT9Yr/jA3Jiv/8' .
    'L19R3JvI1zhQV7BMY0DpZ99oDDh0/UKNAVHT7oH/n4D/OwLAfvzh/87HPywGrBCA/6+F/zsCwH784f/Oxz8sBqwQgP/fDv93BID9+MP/+8H/s+H/G+D/OfD/' .
    '8/D/DgEA//8B/l8B/98B/4+D/++A/8+G/zsCwH784f/Oxz8sBqwQgP8Pg/87AsB+/OH/B+H/F8P/98P/4+D/TfD/p+H/6+D//eH/zsc/LAasEID/J8L/HQFg' .
    'P/7wf+fjHxYDVgjA/9fC/x0BYD/+8H/n42/FAPw/H/7/AfzfEQD24w//dz7+YTFghQD8fw/8Pxr+PwL+vwz+73z8rRiA/x+A/x+F/zsCwH784f/Oxz8sBqwQ' .
    'gP8Pgf+vgP8/B//fAv93Pv5WDMD/74P/74T/OwLAfvzh/87HPywGrBCA//8C/78Z/v8w/H8P/N/5+IfFgBUC8P8Z8H9HANiPP/zf/fgjBqwQgP9Pg/87AsB+' .
    '/OH/zsc/LAasEID/T4T/3wT/r4P/94L/T4f/l8D/U+D/efD/dfD/GPh/Bvz/Dvj/q/D/IfD/PfD/bfD/L+D/jgCwH3/4v/PxD4sBKwTg/xXwf0cA2I8//N/5' .
    '+IfFgBUC8P9T8H9HANiPP/y/4+MP/2+B/6+E/98P/8+D//8M/z8L/18P/x8D/38Z/v86/H8+/D8d/r8G/j8X/u98/MNiwAoB+H8L/N8RAPbjD//v+PjD/yPg' .
    '/1Pg/4fh/44AsB9/+L/z8Q+LASsE4P+r4f8dAgD+/w78PxL+XwD/Hwz/r4L/H4T/dwgA+P8X8H/n4x8WA1YIwP8T4P+OALAff/i/8/EPiwErBOD/f8P/HQFg' .
    'P/7w/46PP/x/qMf/Z8L/OwQA/L8c/h+C/z8L/6+C/z8P/38P/j8B/r8A/p8E/38C/n8R/L8S/t8d/t/f4/+5Afy/P/w/F/5/Hfy/yOP/hQH8v8jj/4Xw//0e' .
    '/4+G/4c8/r8f/h8N/+8N/0/3+H8D/L82gP+nw/8b4P/VHv9PDuD/1R7/T4b/H/b4fwL8/6TH/3/0+H8C/L8M/j8A/j8wgP+Xwf8Hwv8HwP/bPP7/fQD/b/P4' .
    '//fw/yKP/4+E/xfB/+vh/0Ue/x8J/x/m8f+9Afx/mMf/98L/W+H/MfD/bPh/K/x/Ofy/Ff6fDf+Pgf9XePx/UAD/r/D4/yD4fw38PxH+vxP+XwP/b4D/18D/' .
    'l8L/E+H/6R7/bw7g/+ke/2+G//eC/8fC/5sC+H8v+H8T/D8W/v+ux/9bA/j/ux7/b4X//+bx/6gA/v+bx/+j4P/Z8P8L4f9d4f/zPP6fDf/vCv+/EP5/Av6f' .
    'Cf+/Bf6/yeP/J+D/t8D/M+H/7R7/rw/g/+3w/3r4/wr4f1+P/58M4P994f8n4f9r4f+nPf7fCP8/7fH/Io//N8L/e8D/K+H/GfD/4x7/7wH/z4D/V8L/y+H/' .
    'tfD/TwL4fzn8/xP4fy38P9nj/xvh/8ke/5/s8f+N8P9Uj/9HBvD/VI//R8L/p3v8fxb8/0H4fyn8fzr8fyL8Pwn+/4zH/+cH8P9n4P9XwP8vh/8P9/h/ZAD/' .
    'H+7x/0j4f4vH/0Pw/xb4/zz4/zmP/4fg/595/H8A/H83/P8a+P/d8P/74P8D4P+j4f9r4P8r4f8Pw/+3w/93wv9Xwv93FX942+KCqXFlG7Z2rr62Nqr0PxXl' .
    'gA8=';

function hg_vid(mixed $value): string {
    if(!is_string($value)||!preg_match('/\A[0-9]{10,24}\z/',$value))throw new InvalidArgumentException('请通过 ?vid=... 传入 10–24 位数字视频 ID');
    return $value;
}
function hg_profile(): array {
    // 单文件内置原固定设备，没有外部 config.json，也不随机生成新设备。
    return [[
        'aid'=>'8662',
        'compliance_status'=>'0',
        'is_android_pad_screen'=>'0',
        'device_brand'=>'Samsung',
        'cdid'=>'2ba8aa73-ef9e-497f-9150-dea9b1291048',
        'iid'=>'3788268572512444',
        'rom_version'=>'V417IR release-keys',
        'version_code'=>'72932',
        'dpi'=>'480',
        'device_id'=>'3788268572508348',
        'host_abi'=>'arm64-v8a',
        'channel'=>'googleplay',
        'resolution'=>'1080*1920',
        'os_version'=>'15',
        'version_name'=>'7.2.9.32',
        'update_version_code'=>'72932',
        'language'=>'en',
        'player_so_load'=>'1',
        'manifest_version_code'=>'72932',
        'pv_player'=>'72932',
        'os'=>'android',
        'os_api'=>'35',
        'dragon_device_type'=>'phone',
        'need_personal_recommend'=>'1',
        'ac'=>'wifi',
        'app_name'=>'novelread',
        'device_type'=>'SM-S938U',
        'ssmix'=>'a',
        'device_platform'=>'android',
    ], [
        'user-agent'=>'com.phoenix.read.oversea.gp/72932 (Linux; U; Android 15; en_US; SM-S938U; Build/V417IR;tt-ok/3.12.13.20)',
        'passport-sdk-version'=>'5051452',
        'sdk-version'=>'2',
        'x-tt-store-region'=>'kh',
        'x-tt-store-region-src'=>'uid',
    ]];
}
/** All callers sign the final encoded URL and the exact transmitted body bytes.
 * Only known App paths are accepted. No remote signing service, device rotation,
 * retries or persistent cache. GET has no stale body MD5 header.
 */
function hg_app_request(string $method,string $path,array $extraQuery=[],?array $payload=null): array {
    $allowed=[
        'GET'=>['/reading/bookapi/search/tab/v','/reading/bookapi/bookmall/cell/change/v'],
        'POST'=>['/reading/distribution/category/landpage/v','/novel/player/multi_video_detail/v1/','/novel/player/video_model/v1/'],
    ];
    if(!in_array($path,$allowed[$method]??[],true)||($method==='GET'&&$payload!==null))throw new InvalidArgumentException('不支持的平台请求');
    foreach(['curl','zlib'] as $ext)if(!extension_loaded($ext))throw new RuntimeException("PHP 缺少扩展：$ext");
    [$query,$headers]=hg_profile();$query=array_merge($query,$extraQuery);
    $ts=time();$query['_rticket']=(string)(int)floor(microtime(true)*1000);
    $url='https://api5-normal-sinfonlinec.fqnovel.com'.$path.'?'.http_build_query($query,'','&',PHP_QUERY_RFC3986);
    $body=$payload===null?'':json_encode($payload,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR);
    $headers['content-type']='application/json; charset=utf-8';
    if($payload!==null)$headers['x-ss-stub']=strtoupper(md5($body));
    $headers=array_merge($headers,hg_hm($url,$body,$ts),[
        'x-khronos'=>(string)$ts,'x-gorgon'=>hg_gorgon(parse_url($url,PHP_URL_QUERY),$body,$ts,random_int(0,65535)),
        'x-argus'=>base64_encode(pack('V',$ts)),'x-ladon'=>base64_encode(pack('N',$ts))]);
    $list=[];foreach($headers as $k=>$v)$list[]="$k: $v";
    $handle=curl_init($url);$raw='';
    $options=[CURLOPT_CUSTOMREQUEST=>$method,CURLOPT_HTTPHEADER=>$list,
        CURLOPT_CONNECTTIMEOUT=>8,CURLOPT_TIMEOUT=>30,CURLOPT_FOLLOWLOCATION=>false,CURLOPT_PROTOCOLS=>CURLPROTO_HTTPS,
        CURLOPT_SSL_VERIFYPEER=>true,CURLOPT_SSL_VERIFYHOST=>2,CURLOPT_ENCODING=>'',
        CURLOPT_WRITEFUNCTION=>static function($ch,string $part)use(&$raw):int{if(strlen($raw)+strlen($part)>4*1024*1024)return 0;$raw.=$part;return strlen($part);}];
    if($payload!==null)$options[CURLOPT_POSTFIELDS]=$body;
    curl_setopt_array($handle,$options);
    $ok=curl_exec($handle);$status=(int)curl_getinfo($handle,CURLINFO_RESPONSE_CODE);$error=curl_error($handle);curl_close($handle);
    if($ok===false)throw new RuntimeException('平台连接失败：'.$error);
    if($status!==200)throw new RuntimeException("平台 HTTP $status");
    $json=json_decode($raw,true,512,JSON_THROW_ON_ERROR|JSON_BIGINT_AS_STRING);
    if(!is_array($json)||array_is_list($json))throw new RuntimeException('平台响应不是 JSON 对象');
    $base=$json['BaseResp']??[];
    if(isset($base['StatusCode'])&&!in_array($base['StatusCode'],[0,'0'],true))throw new RuntimeException('平台业务错误 '.$base['StatusCode'].'：'.($base['StatusMessage']??''));
    foreach(['code','Code','status_code','err_no','error_code'] as $name)
        if(isset($json[$name])&&!in_array($json[$name],[0,'0'],true))throw new RuntimeException('平台业务错误 '.$json[$name].'：'.($json['message']??$json['Message']??$json['msg']??''));
    if(!empty($json['error']))throw new RuntimeException('平台返回错误');
    return $json;
}
function hg_json(mixed $value,int $status=200): void {
    http_response_code($status);header('Content-Type: application/json; charset=utf-8');header('Cache-Control: no-store');
    echo json_encode($value,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_INVALID_UTF8_SUBSTITUTE|JSON_THROW_ON_ERROR);
}

// common.php is a library; direct web requests expose no configuration.
if(realpath($_SERVER['SCRIPT_FILENAME']??'')===__FILE__){http_response_code(404);exit;}
