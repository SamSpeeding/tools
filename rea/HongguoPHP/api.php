<?php
declare(strict_types=1);
/** Public API: all actions are GET, with HEAD additionally supported by media.
 * Discovery mirrors the verified App requests; no website/vendor services.
 * video.php / play.php remain compatibility entry points and implementation files.
 */
require_once __DIR__.'/video.php';

const HG_RANKS = [
    'all'=>['all',['ranklist_hot_sc','ranklist_hot_play_sc','ranklist_new_rank_sc']],
    'human'=>['human',['human_hot_sc','human_hot_play','human_new_rank']],
    'comic'=>['comic_series_rank',['comic_series_hot_rank','comic_series_hot_play','comic_series_new_rank']],
    'ai'=>['ai_playlet',['ai_playlet_hot_sc','ai_playlet_hot_play','ai_playlet_new_rank']],
];
const HG_GENRES = ['short_play'=>'default','comic_series'=>'comic_series','ai_series'=>'ai_series'];
const HG_DIMENSIONS = ['genre','category_dim_theme','category_dim_role','category_dim_epoch','sort','gender','creation_status','online_time'];

function hg_api_string(array $p,string $key,string $default='',int $max=16384): string {
    $v=$p[$key]??$default;
    if(!is_string($v)||strlen($v)>$max||!preg_match('//u',$v))throw new InvalidArgumentException("$key 参数格式无效");
    return trim($v);
}
function hg_api_choice(array $p,string $key,array $values,string $default): string {
    $v=hg_api_string($p,$key,$default,100);
    if(!in_array($v,$values,true))throw new InvalidArgumentException("$key 应为 ".implode(' / ',$values));
    return $v;
}
function hg_api_object(array $p,string $key): array {
    $text=hg_api_string($p,$key);
    if($text==='')return [];
    try{$v=json_decode($text,true,32,JSON_THROW_ON_ERROR|JSON_BIGINT_AS_STRING);}
    catch(JsonException){throw new InvalidArgumentException("$key 应为 JSON 对象");}
    if(!is_array($v)||!str_starts_with($text,'{'))throw new InvalidArgumentException("$key 应为 JSON 对象");
    return $v;
}
function hg_api_offset(mixed $v): int {
    if(!(is_int($v)||(is_string($v)&&preg_match('/^\d{1,7}$/D',$v)))||(int)$v<0||(int)$v>1000000)
        throw new InvalidArgumentException('offset 应为 0–1000000 的整数');
    return (int)$v;
}
function hg_api_cursor(array $p): array {
    $c=hg_api_object($p,'cursor');$c['offset']=hg_api_offset($c['offset']??($p['offset']??0));
    foreach(['passback','search_id'] as $k)if(isset($c[$k]))$c[$k]=hg_api_string($c,$k);
    return $c;
}
function hg_api_text(mixed ...$values): string {
    foreach($values as $v)if(is_scalar($v)&&trim((string)$v)!=='')return trim(strip_tags((string)$v));
    return '';
}
function hg_api_cover(mixed $v): string {
    if(is_array($v)){
        foreach(['url','uri','url_list'] as $k)if(isset($v[$k]))return hg_api_cover($v[$k]);
        foreach($v as $x)if(($url=hg_api_cover($x))!=='')return $url;
    }
    return is_string($v)&&str_starts_with($v,'https://')?$v:'';
}
function hg_api_more(mixed $v): bool {return in_array($v,[true,1,'1','true'],true);}
function hg_api_link(array $params): string {
    $path=str_replace('\\','/',dirname($_SERVER['SCRIPT_NAME']??''));
    $path=($path==='.'||$path==='/'?'':rtrim($path,'/')).'/api.php';
    $host=$_SERVER['HTTP_HOST']??'';
    $origin=preg_match('/^[a-zA-Z0-9.\-\[\]:]+$/D',$host)?((!empty($_SERVER['HTTPS'])&&$_SERVER['HTTPS']!=='off')?'https://':'http://').$host:'';
    return $origin.$path.'?'.http_build_query($params,'','&',PHP_QUERY_RFC3986);
}
function hg_api_page(array $items,bool $more,?array $cursor,array $extra=[]): array {
    return array_merge(['items'=>array_values($items),'has_more'=>$more,'next_cursor'=>$cursor],$extra);
}
function hg_api_unique(array $items): array {
    $out=[];foreach($items as $item)if($item!==null&&!isset($out[$item['series_id']]))$out[$item['series_id']]=$item;
    return array_values($out);
}
function hg_api_card(mixed $v): ?array {
    if(!is_array($v))return null;$inner=$v['video_detail']??[];
    $sid=$v['series_id']??$v['series_id_str']??$inner['series_id']??$v['book_id']??'';
    if(!is_scalar($sid)||!preg_match('/^\d{10,24}$/D',(string)$sid))return null;
    return ['series_id'=>(string)$sid,'title'=>hg_api_text($v['title']??null,$v['series_title']??null,$v['name']??null,$inner['series_title']??null,$sid),
        'cover'=>hg_api_cover($v['cover']??$v['series_cover']??$inner['series_cover']??''),
        'episode_cnt'=>$v['episode_cnt']??$inner['episode_cnt']??0,'score'=>hg_api_text($v['score']??null,$inner['score']??null),
        'intro'=>hg_api_text($v['video_desc']??null,$v['series_intro']??null,$inner['series_intro']??null),
        'status'=>hg_api_text($v['series_status']??null)];
}
function hg_api_search_card(array $cell): ?array {
    $sid=$cell['book_id']??$cell['search_result_id']??'';
    if(!is_scalar($sid)||!preg_match('/^\d{10,24}$/D',(string)$sid))return null;
    $detail=$cell['video_detail']??[];$v=$cell['video_data']??[];
    if(is_array($v)&&array_is_list($v))$v=$v[0]??[];
    if(!is_array($v))$v=[];$inner=$v['video_detail']??[];
    $count=$detail['episode_cnt']??$v['episode_cnt']??$inner['episode_cnt']??0;
    if(!$count)return null;
    return ['series_id'=>(string)$sid,'title'=>hg_api_text($inner['series_title']??null,$detail['series_title']??null,$v['title']??null,$cell['search_high_light']['title']['text']??null),
        'episode_cnt'=>$count,'intro'=>hg_api_text($inner['series_intro']??null,$detail['series_intro']??null),
        'score'=>$v['score']??$inner['score']??'','play_cnt'=>$v['play_cnt']??$inner['series_play_cnt']??0,
        'hot'=>$v['rec_text']??'','cover'=>hg_api_cover($v['cover']??$inner['series_cover']??''),'vid'=>(string)($v['vid']??'')];
}
function hg_api_search_items(array $cells): array {
    $out=[];
    foreach($cells as $cell){
        if(!is_array($cell))continue;
        if($item=hg_api_search_card($cell))$out[]=array_merge($item,['source_type'=>'search']);
        $ranking=$cell['lynx_data']??null;
        if(is_string($ranking))$ranking=json_decode($ranking,true,512,JSON_BIGINT_AS_STRING);
        foreach(is_array($ranking)?($ranking['cell_data']??[]):[] as $child)
            foreach($child['video_data']??[] as $video){
                if(!is_array($video))continue;
                $sid=$video['series_id']??$video['video_detail']['series_id']??'';
                if($item=hg_api_search_card(['book_id'=>$sid,'video_data'=>[$video]]))$out[]=array_merge($item,['source_type'=>'ranking']);
            }
        foreach($cell['video_data']??[] as $video){
            if(!is_array($video))continue;
            foreach($video['video_detail']['video_detail_list']??[] as $detail){
                if(!is_array($detail))continue;
                if($item=hg_api_search_card(['book_id'=>$detail['series_id_str']??$detail['series_id']??'','video_detail'=>$detail]))$out[]=array_merge($item,['source_type'=>'related_video']);
            }
        }
    }
    return hg_api_unique($out);
}
function hg_api_detail(array $raw,string $sid): array {
    $data=$raw['data'][$sid]['video_data']??null;
    if(!is_array($data)||!isset($data['video_list'])||!is_array($data['video_list']))throw new RuntimeException('平台详情结构不完整');
    $episodes=[];$issues=[];$indices=[];$vids=[];
    foreach($data['video_list'] as $i=>$rawEpisode){
        $ep=is_array($rawEpisode)?$rawEpisode:[];
        $index=filter_var($ep['vid_index']??null,FILTER_VALIDATE_INT,['options'=>['min_range'=>1]]);
        $vid=is_scalar($ep['vid']??null)?(string)$ep['vid']:'';
        if($index===false){$issues[]='第'.($i+1).'条记录缺少有效集号';$index=null;}
        if(!preg_match('/^\d{10,24}$/D',$vid)){$issues[]='第'.($i+1).'条记录缺少有效 vid';$vid='';}
        if($index!==null&&isset($indices[$index]))$issues[]='分集序号重复';
        if($vid!==''&&isset($vids[$vid]))$issues[]='分集 vid 重复';
        if($index!==null)$indices[$index]=true;if($vid!=='')$vids[$vid]=true;
        $episodes[]=array_merge($ep,['index'=>$index,'vid'=>$vid,'title'=>hg_api_text($ep['title']??null),
            'model_url'=>$vid!==''?hg_api_link(['action'=>'video','vid'=>$vid]):null,
            'play_url'=>$vid!==''?hg_api_link(['action'=>'play','vid'=>$vid,'quality'=>'1080p']):null,
            'download_url'=>$vid!==''?hg_api_link(['action'=>'download','vid'=>$vid,'quality'=>'1080p']):null]);
    }
    usort($episodes,fn($a,$b)=>($a['index']??PHP_INT_MAX)<=>($b['index']??PHP_INT_MAX));
    $expected=filter_var($data['episode_cnt']??null,FILTER_VALIDATE_INT,['options'=>['min_range'=>1]]);
    if(!$episodes)$issues[]='平台未返回分集';
    if($expected!==false&&count($episodes)!==$expected)$issues[]='返回分集数量与平台总集数不一致';
    unset($data['video_list']);
    $meta=array_merge($data,['series_id'=>$sid,'title'=>hg_api_text($data['series_title']??null,$sid),
        'intro'=>hg_api_text($data['series_intro']??null),'episode_cnt'=>$expected!==false?$expected:count($episodes),
        'status'=>($data['series_status']??null)===1?'完结':'连载中','cover'=>hg_api_cover($data['series_cover']??'')]);
    return ['series_id'=>$sid,'meta'=>$meta,'episodes'=>$episodes,'complete'=>!$issues,'issues'=>array_values(array_unique($issues))];
}

/** Injectable request boundary is for replay tests; it is never a public parameter. */
function hg_api_dispatch(array $p,?callable $request=null): array {
    $request??='hg_app_request';
    $action=hg_api_choice($p,'action',['search','rank','filters','category','latest','detail','episodes'],'search');
    if(in_array($action,['detail','episodes'],true)){
        $sid=hg_api_string($p,'series_id','',24);
        if(!preg_match('/^\d{10,24}$/D',$sid))throw new InvalidArgumentException('series_id 应为 10–24 位数字');
        $raw=$request('POST','/novel/player/multi_video_detail/v1/',[],['biz_param'=>[
            'detail_page_version'=>0,'disable_digg_stat'=>false,'disable_video_relate_book'=>false,
            'image_shrink_datas_str'=>"W3siaW1hZ2VfdHlwZSI6MywiaW1hZ2Vfd2lkdGgiOjkwMCwic2hyaW5rX3R5cGUiOjN9LHsiaW1h\nZ2VfdHlwZSI6NCwiaW1hZ2Vfd2lkdGgiOjU0LCJzaHJpbmtfdHlwZSI6NH1d\n",
            'need_all_video_definition'=>false,'need_mp4_align'=>false,'screen_width_px'=>'900','source'=>7,'use_os_player'=>false,'use_server_dns'=>false],
            'series_id'=>$sid]);
        $detail=hg_api_detail($raw,$sid);
        return $action==='detail'?$detail:['series_id'=>$sid,'title'=>$detail['meta']['title'],'episode_cnt'=>$detail['meta']['episode_cnt'],
            'complete'=>$detail['complete'],'issues'=>$detail['issues'],'episodes'=>$detail['episodes']];
    }
    $cursor=hg_api_cursor($p);$offset=$cursor['offset'];
    if($action==='search'){
        $q=hg_api_string($p,'q','',400);
        if($q===''||preg_match_all('/./us',$q)>100)throw new InvalidArgumentException('q 应为 1–100 个字符');
        $query=['query'=>$q,'tab_name'=>'feed','search_source'=>'1','offset'=>(string)$offset,'count'=>'0','use_correct'=>'true'];
        foreach(['passback','search_id'] as $k)if(!empty($cursor[$k]))$query[$k]=$cursor[$k];
        $raw=$request('GET','/reading/bookapi/search/tab/v',$query);
        if(!isset($raw['search_tabs'])||!is_array($raw['search_tabs']))throw new RuntimeException('平台搜索结构不完整');
        $tab=$raw['search_tabs'][0]??[];$cells=$tab['data']??[];
        if(!is_array($cells))throw new RuntimeException('平台搜索列表格式错误');
        $next=['offset'=>$tab['next_offset']??$offset,'passback'=>$tab['passback']??($cursor['passback']??''),'search_id'=>$tab['search_id']??($cursor['search_id']??'')];
        $more=hg_api_more($tab['has_more']??false);$warnings=[];
        $old=['offset'=>$offset,'passback'=>$cursor['passback']??'','search_id'=>$cursor['search_id']??''];
        if($more&&(!$cells||$next==$old)){$more=false;$warnings[]='平台游标未推进，停止翻页';}
        $out=hg_api_page(hg_api_search_items($cells),$more,$more?$next:null,['query'=>$q,'warnings'=>$warnings]);
    }elseif($action==='rank'){
        $category=hg_api_choice($p,'category',array_keys(HG_RANKS),'all');$board=hg_api_choice($p,'board',['recommend','hot','new'],'hot');
        [$selected,$boards]=HG_RANKS[$category];
        $hex=bin2hex(random_bytes(16));$uuid=substr($hex,0,8).'-'.substr($hex,8,4).'-4'.substr($hex,13,3).'-'.dechex((hexdec($hex[16])&3)|8).substr($hex,17,3).'-'.substr($hex,20);
        $query=['cell_id'=>'7470092475068071998','tab_type'=>'26','client_req_type'=>'2','client_template'=>'2','screen_width_px'=>'1350','session_uuid'=>$uuid,
            'selected_items'=>$selected,'sub_selected_items'=>$boards[array_search($board,['recommend','hot','new'],true)]];
        if($offset)$query['offset']=(string)$offset;
        $raw=$request('GET','/reading/bookapi/bookmall/cell/change/v',$query);
        $data=$raw['data']['cell_view']??null;
        if(!is_array($data)||!isset($data['cell_data'])||!is_array($data['cell_data']))throw new RuntimeException('平台榜单结构不完整');
        $items=[];foreach($data['cell_data'] as $cell){$videos=$cell['video_data']??[];
            if(is_array($videos))foreach(array_is_list($videos)?$videos:[$videos] as $v)$items[]=hg_api_card($v);}
        $next=$data['next_offset']??null;$more=hg_api_more($data['has_more']??false)&&$next!==null&&(string)$next!==(string)$offset;
        $out=hg_api_page(hg_api_unique($items),$more,$more?['offset'=>$next]:null,['category'=>$category,'board'=>$board]);
    }else{
        $genre=hg_api_choice($p,'genre',array_keys(HG_GENRES),'short_play');$panel=$action==='filters';$latest=$action==='latest';
        $selected=array_fill_keys(HG_DIMENSIONS,[]);
        foreach(hg_api_object($p,'selections') as $key=>$values){
            if(!in_array($key,HG_DIMENSIONS,true)||$key==='genre'||!is_array($values)||!array_is_list($values)||count($values)>30)
                throw new InvalidArgumentException('selections 包含无效维度或选项列表');
            foreach($values as $value)if(!is_string($value)||strlen($value)>100)throw new InvalidArgumentException('筛选选项应为字符串 ID');
            $selected[$key]=$values;
        }
        $selected['genre']=[$genre];if(!$selected['sort'])$selected['sort']=['online_time'];
        if($latest){$selected=array_fill_keys(HG_DIMENSIONS,[]);$selected['genre']=[$genre];$selected['sort']=['online_time'];}
        if($panel){$selected=array_fill_keys(array_diff(HG_DIMENSIONS,['creation_status']),[]);$selected['genre']=[$genre];}
        $raw=$request('POST','/reading/distribution/category/landpage/v',[],['filter_ids'=>'','req_scene'=>HG_GENRES[$genre],
            'offset'=>$offset,'need_selector_panel'=>$panel,'limit'=>$panel?1:18,'select_items'=>$selected,'session_id'=>'',
            'req_type'=>$panel?'default':'only_content','client_req_type'=>3]);
        $data=$raw['data']??null;
        if(!is_array($data))throw new RuntimeException('平台分类结构不完整');
        if($panel){
            if(!isset($data['selector_rows'])||!is_array($data['selector_rows']))throw new RuntimeException('平台未返回筛选选项');
            return ['genre'=>$genre,'rows'=>$data['selector_rows']];
        }
        if(!isset($data['video_data'])||!is_array($data['video_data']))throw new RuntimeException('平台未返回剧目列表');
        $videos=$data['video_data'];$more=hg_api_more($data['has_more']??false)&&count($videos)>0;
        // Cursor counts original platform rows, not deduplicated display cards.
        $out=hg_api_page(hg_api_unique(array_map('hg_api_card',$videos)),$more,$more?['offset'=>$offset+count($videos)]:null,
            ['genre'=>$genre,'raw_count'=>count($videos),'selections'=>$selected]);
    }
    foreach($out['items'] as &$item)$item['detail_url']=hg_api_link(['action'=>'detail','series_id'=>$item['series_id']]);unset($item);
    $nextParams=$p;unset($nextParams['offset']);$nextParams['action']=$action;
    $nextParams['cursor']=json_encode($out['next_cursor'],JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR);
    $out['next_url']=$out['has_more']?hg_api_link($nextParams):null;
    return $out;
}

function hg_api_safe_numbers(mixed $v): mixed {
    if(is_array($v))return array_map('hg_api_safe_numbers',$v);
    return is_int($v)&&($v>9007199254740991||$v< -9007199254740991)?(string)$v:$v;
}
function hg_api_main(): void {
    ini_set('display_errors','0');header('X-Content-Type-Options: nosniff');
    try{
        $action=hg_api_string($_GET,'action','',30);$method=$_SERVER['REQUEST_METHOD']??'GET';
        if(in_array($action,['play','download'],true)){
            require_once __DIR__.'/play.php';
            $_GET['download']=$action==='download'?'1':'0';hg_playMain();return;
        }
        if($method!=='GET'){header('Allow: GET');hg_json(['code'=>405,'message'=>'只支持 GET','error'=>'只支持 GET'],405);return;}
        if($action==='video'){header('X-Model-API: video_model');hg_json(hg_model(hg_vid($_GET['vid']??null)));return;}
        if(!in_array($action,['search','rank','filters','category','latest','detail','episodes'],true))throw new InvalidArgumentException('action 应为 search/rank/filters/category/latest/detail/episodes/video/play/download');
        hg_json(['code'=>0,'message'=>'success','action'=>$action,'data'=>hg_api_safe_numbers(hg_api_dispatch($_GET))]);
    }catch(Throwable $e){
        $status=$e instanceof InvalidArgumentException?400:502;
        hg_json(['code'=>$status,'message'=>$e->getMessage(),'error'=>$e->getMessage()],$status);
    }
}
if(realpath($_SERVER['SCRIPT_FILENAME']??'')===__FILE__)hg_api_main();
