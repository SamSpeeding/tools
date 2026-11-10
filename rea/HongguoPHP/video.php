<?php
declare(strict_types=1);
/** Single-model endpoint; all signing and HTTP code is shared in common.php.
 * GET /video.php?vid=... — preserves the original platform JSON envelope.
 * Never calls either batch model endpoint. play.php reuses hg_model directly.
 */
require_once __DIR__.'/common.php';

function hg_model(string $vid): array {
    hg_vid($vid);
    $json=hg_app_request('POST','/novel/player/video_model/v1/',[],[
        'biz_param'=>['detail_page_version'=>0,'device_level'=>3,'disable_digg_stat'=>false,
            'disable_video_relate_book'=>false,'need_all_video_definition'=>true,'need_mp4_align'=>false,
            'use_os_player'=>false,'use_server_dns'=>false,'video_platform'=>1024],'video_id'=>$vid]);
    $model=$json['data']['video_model']??null;
    if(is_string($model))$model=json_decode($model,true,512,JSON_THROW_ON_ERROR|JSON_BIGINT_AS_STRING);
    if(!is_array($model)||empty($model['video_list']))throw new RuntimeException('平台没有返回可用的视频模型');
    $json['data']['video_model']=$model;return $json;
}
function hg_modelMain(): void {
    ini_set('display_errors','0');
    try {
        if(($_SERVER['REQUEST_METHOD']??'GET')!=='GET'){header('Allow: GET');hg_json(['error'=>'只支持 GET'],405);return;}
        $vid=hg_vid(PHP_SAPI==='cli'?($GLOBALS['argv'][1]??null):($_GET['vid']??null));
        header('X-Model-API: video_model');hg_json(hg_model($vid));
    } catch(InvalidArgumentException $e){hg_json(['error'=>$e->getMessage()],400);}
      catch(Throwable $e){hg_json(['error'=>$e->getMessage()],502);}
}
if(realpath($_SERVER['SCRIPT_FILENAME']??'')===__FILE__)hg_modelMain();
