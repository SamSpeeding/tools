<?php
declare(strict_types=1);
/**
 * 内存分段解密代理。PHP 8.1+ / 64 位，扩展 curl、zlib、openssl。
 * 依赖同目录 video.php、common.php；无需 Python、Java、JAR、原 SO 或签名服务。
 * php -S 127.0.0.1:8080 -t /path/to/HongguoPHP
 * 统一入口播放：/api.php?action=play&vid=7689903116275174462
 * 统一入口下载：/api.php?action=download&vid=7689903116275174462
 * 原 play.php?vid=... 链接仍保留兼容。
 * 清晰度：&quality=720p （默认 1080p；不存在时明确报错，不暗中降级）。
 * GET / HEAD / 单段 Range，支持拖动；输出长度、样本偏移均保持不变。
 * 每个请求重新获取模型。只保留少量 CDN 块、moov 索引和样本表在内存，
 * 不写 MP4/临时文件/模型缓存。客户端保存的是完整解密 MP4，未转码。
 * 源 HEVC/H.265 需要浏览器/系统支持；支持 CENC AES-CTR 非分片 MP4。
 * Nginx 部署须关闭 fastcgi_buffering、gzip，否则中间层可能缓冲或落盘。
 * PHP 内置服务器用于本地验证，正式并发使用 PHP-FPM。
 */
require_once __DIR__ . '/video.php';

function hg_require(bool $ok, string $message = '视频索引格式无效'): void {
    if (!$ok) throw new RuntimeException($message);
}
function hg_uint(string $data, int $offset, int $width = 4): int {
    hg_require($offset >= 0 && $offset + $width <= strlen($data));
    $value = unpack(match ($width) {2=>'n',4=>'N',8=>'J'}, substr($data,$offset,$width))[1];
    hg_require($value >= 0, '视频数值超过 64 位整数范围');
    return $value;
}
function hg_boxes(string $data, int $start = 0, ?int $end = null): Generator {
    $end ??= strlen($data);
    hg_require(0 <= $start && $start <= $end && $end <= strlen($data));
    while ($start < $end) {
        hg_require($start+8 <= $end);
        $size=hg_uint($data,$start);$kind=substr($data,$start+4,4);$header=8;
        if ($size===1) {hg_require($start+16 <= $end);$size=hg_uint($data,$start+8,8);$header=16;}
        elseif ($size===0) $size=$end-$start;
        hg_require($size >= $header && $size <= $end-$start);
        yield ['kind'=>$kind,'start'=>$start,'body'=>$start+$header,'end'=>$start+$size];
        $start+=$size;
    }
}
function hg_child(string $data, array $box, string $kind, bool $optional=false): ?array {
    $found=null;
    foreach(hg_boxes($data,$box['body'],$box['end']) as $child) {
        if($child['kind']!==$kind) continue;
        hg_require($found===null,'视频索引存在重复结构');$found=$child;
    }
    hg_require($found!==null || $optional,"视频缺少 $kind 索引");
    return $found;
}
function hg_numbers(string $data,array $box,int $offset,int $count,int $width=4): array {
    // PHP 数组有额外开销；约束样本数，避免异常索引耗尽内存。
    hg_require($count>=0 && $count<=200000 && $offset>=0 && $box['body']+$offset+$count*$width <= $box['end']);
    if($count===0)return [];
    $values=array_values(unpack(match($width){4=>'N*',8=>'J*'},substr($data,$box['body']+$offset,$count*$width)));
    foreach($values as $value)hg_require($value>=0);
    return $values;
}
function hg_samples(string $data,array $stbl,int $total): array {
    $stsz=hg_child($data,$stbl,'stsz');[$fixed,$count]=hg_numbers($data,$stsz,4,2);
    hg_require($count>0 && $count<=100000,'视频样本数超过当前实现上限');
    $sizes=$fixed?array_fill(0,$count,$fixed):hg_numbers($data,$stsz,12,$count);
    $stco=hg_child($data,$stbl,'stco',true)??hg_child($data,$stbl,'co64');
    $chunks=hg_numbers($data,$stco,8,hg_numbers($data,$stco,4,1)[0],$stco['kind']==='co64'?8:4);
    $stsc=hg_child($data,$stbl,'stsc');
    $runs=array_chunk(hg_numbers($data,$stsc,8,hg_numbers($data,$stsc,4,1)[0]*3),3);
    hg_require(count($runs)>0 && $runs[0][0]===1 && count($chunks)>0);
    $last=0;
    foreach($runs as [$first,$per,$desc]) {
        hg_require($first>$last && $first<=count($chunks) && $per>0 && $per<=$count && $desc===1,'不支持此视频的样本描述切换');$last=$first;
    }
    $result=[];$sample=0;$run=0;
    foreach($chunks as $index=>$offset) {
        if(isset($runs[$run+1]) && $index+1===$runs[$run+1][0])$run++;
        for($i=0;$i<$runs[$run][1];$i++) {
            hg_require($sample<$count);$size=$sizes[$sample++];
            hg_require($size>0 && $size<=16*1024*1024 && $offset<=$total-$size,'视频样本位置无效');
            $result[]=[$offset,$size];$offset+=$size;
        }
    }
    hg_require($sample===$count);return $result;
}

function hg_unwrap(string $raw,int $flag): ?string {
    $length=strlen($raw);if($length<3)return null;
    $tag=ord($raw[0])^ord($raw[1])^ord($raw[2]);$suffixLength=$tag-48;$payloadLength=$length-$tag+47;
    if($suffixLength<1 || $length-$suffixLength-2<0 || $payloadLength<1 || 1+$payloadLength>$length)return null;
    $even=ord($raw[$length-$suffixLength-2]);$odd=ord($raw[$length-$suffixLength-1]);$suffix='';
    for($i=0;$i<$suffixLength;$i++)$suffix.=chr($odd^$even^ord($raw[$length-$suffixLength+$i]));
    foreach(['app_v2','web_v2'] as $marker) {
        $same=true;
        for($i=0;$i<$suffixLength;$i++) {
            $a=$suffix[$i];$b=$marker[$i]??"\0";
            if($a!==$b){$same=false;break;}if($a==="\0")break;
        }
        if($same)return null;
    }
    $decoded=substr($raw,1,$payloadLength);$odd=85;$even=250;
    for($i=0;$i<$payloadLength;$i++) {
        $current=ord($decoded[$i]);$bits=substr_count(decbin($i & 0xffffffff),'1');
        $nextEven=$current;$nextOdd=$odd;
        if($i & 1){$nextEven=$even;$nextOdd=$current;$even=$odd;}
        $decoded[$i]=chr((($flag?$bits+21:-21-$bits)+($even^$current)) & 255);
        $odd=$nextOdd;$even=$nextEven;
    }
    $first=ord($decoded[0]);$padding=($first>=48 && $first<=57)?$first-48:(($first>=97 && $first<=122)?$first-87:null);
    if($padding===null || $payloadLength-$padding<2)return null;
    return substr($decoded,1,$payloadLength-$padding-1);
}
function hg_counter(string $iv,int $blocks): string {
    hg_require(strlen($iv)===16 && $blocks>=0);
    for($i=15;$i>=0 && $blocks>0;$i--) {
        $sum=ord($iv[$i])+($blocks & 255);$iv[$i]=chr($sum & 255);$blocks=intdiv($blocks,256)+($sum>>8);
    }
    hg_require($blocks===0,'AES 计数器溢出');return $iv;
}
function hg_nalOk(string $data): bool {
    $size=strlen($data);$p=0;
    while($p+4<=$size){$n=hg_uint($data,$p);if($n===0 || $n>$size-$p-4)return false;$p+=4+$n;}
    return $p===$size;
}

final class HgCdn {
    public const BLOCK=262144;
    private array $urls;
    private array $cache=[];
    private CurlHandle $handle;
    public int $received=0;
    public function __construct(array $urls,public readonly int $total) {
        $this->urls=array_values(array_unique(array_filter($urls,static fn($u)=>is_string($u) && in_array(parse_url($u,PHP_URL_SCHEME),['http','https'],true))));
        hg_require($total>0 && count($this->urls)>0,'视频模型缺少地址或大小');
        $this->handle=curl_init();
    }
    private function block(int $start): string {
        if(isset($this->cache[$start])) {
            $data=$this->cache[$start];unset($this->cache[$start]);$this->cache[$start]=$data;return $data;
        }
        $end=min($this->total-1,$start+self::BLOCK-1);$expected=$end-$start+1;
        foreach($this->urls as $url) {
            if(connection_aborted())throw new RuntimeException('客户端已断开');
            $raw='';$headers=[];
            curl_setopt_array($this->handle,[CURLOPT_URL=>$url,CURLOPT_HTTPGET=>true,
                CURLOPT_HTTPHEADER=>["Range: bytes=$start-$end",'Accept-Encoding: identity'],
                CURLOPT_CONNECTTIMEOUT=>8,CURLOPT_TIMEOUT=>25,CURLOPT_FOLLOWLOCATION=>false,
                CURLOPT_PROTOCOLS=>CURLPROTO_HTTP|CURLPROTO_HTTPS,CURLOPT_SSL_VERIFYPEER=>true,CURLOPT_SSL_VERIFYHOST=>2,
                CURLOPT_HEADERFUNCTION=>static function($ch,string $line)use(&$headers):int {
                    if(str_starts_with($line,'HTTP/'))$headers=[];
                    elseif(str_contains($line,':')){[$k,$v]=explode(':',$line,2);$headers[strtolower(trim($k))]=trim($v);}return strlen($line);
                },
                CURLOPT_WRITEFUNCTION=>static function($ch,string $part)use(&$raw,$expected):int {
                    if(connection_aborted() || strlen($raw)+strlen($part)>$expected)return 0;$raw.=$part;return strlen($part);
                }]);
            $ok=curl_exec($this->handle);$status=(int)curl_getinfo($this->handle,CURLINFO_RESPONSE_CODE);
            if($ok===false || $status!==206 || ($headers['content-range']??'')!=="bytes $start-$end/{$this->total}"
                || !in_array($headers['content-encoding']??'identity',['','identity'],true) || strlen($raw)!==$expected)continue;
            $this->received+=$expected;$this->cache[$start]=$raw;
            while(count($this->cache)>4)unset($this->cache[array_key_first($this->cache)]);
            return $raw;
        }
        throw new RuntimeException('视频分段读取失败（源需支持正确的 Range，或地址已失效）');
    }
    public function read(int $start,int $end): string {
        hg_require(0<=$start && $start<=$end && $end<$this->total);
        $result='';
        while($start<=$end) {
            $base=intdiv($start,self::BLOCK)*self::BLOCK;$block=$this->block($base);$stop=min($end+1,$base+strlen($block));
            $result.=substr($block,$start-$base,$stop-$start);$start=$stop;
        }
        return $result;
    }
}

final class HgMp4 {
    private string $metadata;
    private int $moovStart;
    private array $spans=[];
    private array $videoSamples=[];
    public function __construct(private HgCdn $reader,private ?string $key) {
        [$this->moovStart,$data]=$this->metadata();$this->metadata=$data;
        $root=iterator_to_array(hg_boxes($data))[0];
        hg_require($root['kind']==='moov' && $root['end']===strlen($data));
        hg_require(hg_child($data,$root,'mvex',true)===null,'暂不支持分片 MP4');
        foreach(hg_boxes($data,$root['body'],$root['end']) as $track) {
            if($track['kind']!=='trak')continue;
            $mdia=hg_child($data,$track,'mdia');$hdlr=hg_child($data,$mdia,'hdlr');hg_require($hdlr['body']+12<=$hdlr['end']);
            $handler=substr($data,$hdlr['body']+8,4);if(!in_array($handler,['vide','soun'],true))continue;
            $stbl=hg_child($data,hg_child($data,$mdia,'minf'),'stbl');$stsd=hg_child($data,$stbl,'stsd');
            hg_require(hg_numbers($data,$stsd,4,1)[0]===1,'暂不支持多个编码描述');
            $entries=iterator_to_array(hg_boxes($data,$stsd['body']+8,$stsd['end']));hg_require(count($entries)===1);$entry=$entries[0];
            if(!in_array($entry['kind'],['encv','enca'],true))continue;
            hg_require($key!==null && strlen($key)===16,'视频缺少解密密钥');
            $skip=$entry['kind']==='encv'?78:28;hg_require($entry['body']+$skip<=$entry['end']);
            if($entry['kind']==='enca')hg_require(substr($data,$entry['body']+8,2)==="\0\0",'不支持此音频描述版本');
            $children=$entry;$children['body']+=$skip;
            $sinf=hg_child($data,$children,'sinf');$frma=hg_child($data,$sinf,'frma');hg_require($frma['body']+4===$frma['end']);
            $codec=substr($data,$frma['body'],4);hg_require(in_array($codec,['hvc1','hev1','avc1','mp4a'],true),'不支持此编码');
            $schm=hg_child($data,$sinf,'schm');hg_require($schm['body']+8<=$schm['end'] && substr($data,$schm['body']+4,4)==='cenc','不支持此加密方式');
            $tenc=hg_child($data,hg_child($data,$sinf,'schi'),'tenc');
            hg_require($tenc['body']+24<=$tenc['end'] && ord($data[$tenc['body']])===0 && ord($data[$tenc['body']+6])===1);
            $ivSize=ord($data[$tenc['body']+7]);hg_require(in_array($ivSize,[8,16],true),'不支持此 IV 长度');
            $samples=hg_samples($data,$stbl,$reader->total);
            $senc=hg_child($data,$stbl,'senc',true)??hg_child($data,$track,'senc',true);hg_require($senc!==null,'视频缺少逐样本加密信息');
            [$flags,$count]=hg_numbers($data,$senc,0,2);hg_require(in_array($flags,[0,2],true) && $count===count($samples),'不支持此加密布局');
            $cursor=$senc['body']+8;
            foreach($samples as [$offset,$size]) {
                hg_require($cursor+$ivSize<=$senc['end']);$iv=str_pad(substr($data,$cursor,$ivSize),16,"\0");$cursor+=$ivSize;
                if($flags & 2) {
                    hg_require($cursor+2<=$senc['end']);$pairs=hg_uint($data,$cursor,2);$cursor+=2;hg_require($cursor+$pairs*6<=$senc['end']);
                    $used=$encryptedOffset=0;
                    for($i=0;$i<$pairs;$i++) {
                        $clear=hg_uint($data,$cursor,2);$cipher=hg_uint($data,$cursor+2);$cursor+=6;$used+=$clear;
                        hg_require($used+$cipher<=$size);
                        if($cipher)$this->spans[]=[$offset+$used,$cipher,$iv,$encryptedOffset];
                        $used+=$cipher;$encryptedOffset+=$cipher;
                    }
                    hg_require($used===$size,'子样本长度不一致');
                }else $this->spans[]=[$offset,$size,$iv,0];
                hg_require(count($this->spans)<=200000,'视频加密片段超过当前实现上限');
            }
            hg_require($cursor===$senc['end']);
            if($handler==='vide')$this->videoSamples=array_merge($this->videoSamples,array_slice($samples,0,2));
            $this->patch($entry['start']+4,$codec);$this->patch($sinf['start']+4,'free');$this->patch($senc['start']+4,'free');
            foreach(hg_boxes($data,$stbl['body'],$stbl['end']) as $box)if(in_array($box['kind'],['saio','saiz'],true))$this->patch($box['start']+4,'free');
        }
        hg_require($key===null || count($this->videoSamples)>0,'没有可验证的加密视频样本');
        usort($this->spans,static fn($a,$b)=>$a[0]<=>$b[0]);$end=0;
        foreach($this->spans as [$start,$size]){hg_require($start>=$end,'加密样本范围重叠');$end=$start+$size;}
    }
    private function patch(int $offset,string $value): void {
        for($i=0;$i<strlen($value);$i++)$this->metadata[$offset+$i]=$value[$i];
    }
    private function metadata(): array {
        $offset=0;$total=$this->reader->total;
        for($i=0;$i<256;$i++) {
            hg_require($offset+8<=$total,'视频没有 moov 索引');$h=$this->reader->read($offset,min($offset+15,$total-1));
            $size=hg_uint($h,0);$kind=substr($h,4,4);$min=8;
            if($size===1){$size=hg_uint($h,8,8);$min=16;}elseif($size===0)$size=$total-$offset;
            hg_require($size>=$min && $size<=$total-$offset);hg_require($kind!=='moof','暂不支持分片 MP4');
            if($kind==='moov'){hg_require($size<=16*1024*1024,'视频索引过大');return [$offset,$this->reader->read($offset,$offset+$size-1)];}
            $offset+=$size;
        }
        throw new RuntimeException('视频顶层结构过多');
    }
    public function decrypt(int $start,string $data): string {
        $end=$start+strlen($data);$lo=0;$hi=count($this->spans);
        while($lo<$hi){$mid=intdiv($lo+$hi,2);if($this->spans[$mid][0]<=$start)$lo=$mid+1;else $hi=$mid;}
        for($i=max(0,$lo-1);$i<count($this->spans);$i++) {
            [$offset,$size,$iv,$encryptedOffset]=$this->spans[$i];if($offset>=$end)break;
            $first=max($start,$offset);$last=min($end,$offset+$size);if($first>=$last)continue;
            $skip=$encryptedOffset+$first-$offset;$padding=$skip%16;
            $ciphertext=str_repeat("\0",$padding).substr($data,$first-$start,$last-$first);
            $plain=openssl_decrypt($ciphertext,'aes-128-ctr',$this->key,OPENSSL_RAW_DATA,hg_counter($iv,intdiv($skip,16)));
            hg_require($plain!==false && strlen($plain)===strlen($ciphertext),'AES 解密失败');
            $data=substr_replace($data,substr($plain,$padding),$first-$start,$last-$first);
        }
        $first=max($start,$this->moovStart);$last=min($end,$this->moovStart+strlen($this->metadata));
        if($first<$last)$data=substr_replace($data,substr($this->metadata,$first-$this->moovStart,$last-$first),$first-$start,$last-$first);
        return $data;
    }
    public function read(int $start,int $end): string {return $this->decrypt($start,$this->reader->read($start,$end));}
    public function verify(): void {
        foreach($this->videoSamples as [$offset,$size])hg_require(hg_nalOk($this->read($offset,$offset+$size-1)),'视频与解密参数不匹配');
    }
}

function hg_range(?string $header,int $total): array {
    if($header===null || $header==='')return [0,$total-1,false];
    if(!preg_match('/^bytes=(\d*)-(\d*)$/D',trim($header),$m) || ($m[1]==='' && $m[2]===''))throw new RangeException('仅支持一个有效的 bytes 范围');
    if($m[1]===''){$suffix=(int)$m[2];if($suffix<=0)throw new RangeException('无效后缀范围');$start=max(0,$total-$suffix);$end=$total-1;}
    else {$start=(int)$m[1];$end=$m[2]===''?$total-1:min((int)$m[2],$total-1);}
    if($start>=$total || $end<$start)throw new RangeException('范围超出视频长度');
    return [$start,$end,true];
}
function hg_track(array $model,string $quality): array {
    foreach($model['video_list']??[] as $track)if(($track['video_meta']['definition']??$track['definition']??'')===$quality && (!empty($track['main_url']) || !empty($track['backup_url'])))return $track;
    throw new RuntimeException("此集没有 $quality 地址，请更换 quality 参数");
}
function hg_prepare(array $track): array {
    $reader=new HgCdn([$track['main_url']??null,$track['backup_url']??null],(int)($track['video_meta']['size']??$track['size']??0));
    $info=$track['encrypt_info']??[];$keys=[null];
    if(!empty($info['encrypt'])) {
        hg_require(($info['encryption_method']??'')==='cenc-aes-ctr' && !empty($info['spade_a']),'不支持此视频加密格式');
        $raw=base64_decode($info['spade_a'],true);hg_require($raw!==false,'无效 spade_a');$keys=[];
        foreach([0,1] as $flag){$key=hg_unwrap($raw,$flag);if(is_string($key) && preg_match('/^[0-9a-f]{32}$/D',$key))$keys[]=hex2bin($key);}
        $keys=array_unique($keys);hg_require(count($keys)>0,'无法解析此集的解密参数');
    }
    $last=null;
    foreach($keys as $key) {
        try{$stream=new HgMp4($reader,$key);$stream->verify();return [$reader,$stream];}catch(RuntimeException $e){$last=$e;}
    }
    throw $last??new RuntimeException('无法准备此集视频');
}
function hg_playMain(): void {
    ini_set('display_errors','0');ini_set('zlib.output_compression','0');set_time_limit(0);
    $started=false;
    try {
        $method=$_SERVER['REQUEST_METHOD']??'GET';
        if(!in_array($method,['GET','HEAD'],true)){header('Allow: GET, HEAD');hg_json(['error'=>'只支持 GET / HEAD'],405);return;}
        $vid=hg_vid($_GET['vid']??null);$quality=$_GET['quality']??'1080p';
        if(!is_string($quality) || !in_array($quality,['360p','480p','540p','720p','1080p'],true))throw new InvalidArgumentException('quality 应为 360p/480p/540p/720p/1080p');
        if(!extension_loaded('openssl'))throw new RuntimeException('PHP 缺少 openssl 扩展');
        $track=hg_track(hg_model($vid)['data']['video_model'],$quality);$total=(int)($track['video_meta']['size']??$track['size']??0);hg_require($total>0,'视频缺少长度');
        // 未提供稳定的 ETag/Last-Modified；If-Range 无法匹配时按 HTTP 规则返回全量。
        try {[$start,$end,$partial]=hg_range($method==='HEAD' || isset($_SERVER['HTTP_IF_RANGE'])?null:($_SERVER['HTTP_RANGE']??null),$total);}
        catch(RangeException $e){header("Content-Range: bytes */$total");header('Accept-Ranges: bytes');hg_json(['error'=>$e->getMessage()],416);return;}
        $reader=$stream=null;$first='';
        if($method!=='HEAD') {
            [$reader,$stream]=hg_prepare($track);
            // 先验证密钥及首块，再发送 200/206；中途失败关闭连接，不能混入 JSON。
            $first=$stream->read($start,min($end,$start+HgCdn::BLOCK-1));
        }
        while(ob_get_level()>0)if(!ob_end_clean())break;
        http_response_code($partial?206:200);header('Content-Type: video/mp4');header('Accept-Ranges: bytes');header('Cache-Control: no-store');
        header('Content-Length: '.($end-$start+1));if($partial)header("Content-Range: bytes $start-$end/$total");
        $disposition=($_GET['download']??'')==='1'?'attachment':'inline';header("Content-Disposition: $disposition; filename=\"$vid-$quality.mp4\"");
        header('X-Content-Type-Options: nosniff');header('X-Accel-Buffering: no');header('X-Model-API: video_model');
        if($reader!==null)header('X-Upstream-Bytes-Before-Body: '.$reader->received);
        if($method==='HEAD')return;
        $started=true;echo $first;flush();$cursor=$start+strlen($first);
        while($cursor<=$end && !connection_aborted()) {
            $stop=min($end,$cursor+HgCdn::BLOCK-1);echo $stream->read($cursor,$stop);flush();$cursor=$stop+1;
        }
    }catch(Throwable $e) {
        if($started || headers_sent()){error_log('Hongguo PHP 流中断：'.$e->getMessage());return;}
        hg_json(['error'=>$e->getMessage()],$e instanceof InvalidArgumentException?400:502);
    }
}
if(realpath($_SERVER['SCRIPT_FILENAME']??'')===__FILE__)hg_playMain();
