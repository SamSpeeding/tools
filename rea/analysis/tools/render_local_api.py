"""Render the manually reviewed API contract together with static route metadata."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
routes=json.loads((ROOT/'analysis/evidence/local-routes.json').read_text())
# body fields, success/branch shape, endpoint errors, side effects.
spec={
'index': ('', '`{service, ui, endpoints}`，旧 API 索引。', '无专门业务错误分支。', '只读。'),
'stats': ('', '`{uptime_s, requests, errors, risk, auth_fail, cache_backend, sign_backends, download_tasks}`；每个签名后端含 `{url, ready, pid}` 或 `{url, ready:false, error}`。', '管理 token 无效：HTTP 401 `需要 admin_token`。', '读取统计，向每个签名后端 `/` 发健康 GET。'),
'ui': ('', 'HTML：`web/index.html`。', '文件缺失为框架/文件层错误。', '只读旧网页。'),
'api_img': ('', '图片二进制；保留允许的 raster Content-Type，HEIC 可转 JPEG；带 Cache-Control、nosniff、CSP。', 'HTTP 400 `图片域名不允许`；HTTP 404 `图片读取失败`（含重定向离开白名单、跳转过多、网络/格式错误）。', '访问白名单图片源并缓存；最多 4 轮跳转检查。'),
'admin_page': ('', 'HTML：`web/admin.html`。', '页面本身没有 `_check_admin`；管理操作另行鉴权。', '只读管理网页。'),
'admin_list_keys': ('', '`{keys, enabled_count}`；keys 为 KeyStore.list() 的透传列表，内部字段未在 handler 中固定。', 'HTTP 401 `admin_token 无效`。', '只读本地 API key 存储。'),
'admin_gen_key': ('', '`{ok:true, key, note}`。', 'HTTP 401 `admin_token 无效`。', '**生成并持久化本地 API key**。`note` 是 query，不是 JSON body。'),
'admin_revoke_key': ('', '`{ok: KeyStore.revoke(...) 的结果}`。', 'HTTP 401 `admin_token 无效`。', '**修改指定 key 的 enabled 状态**；`enable=false` 撤销，`true` 恢复。参数为 query。'),
'admin_delete_key': ('', '`{ok: KeyStore.delete(...) 的结果}`。', 'HTTP 401 `admin_token 无效`。', '**删除本地 API key**。参数为 query。'),
'api_search': ('', '`{query, results}`，条目字段见 REQUEST_CHAIN。', 'HTTP 500 `search失败: ...`。', '调用签名 APP 搜索/缓存。limit 未提供时由 H.search 的环境设置决定，通常 20。'),
'api_rank': ('', '`{board, name, items}`。', '未知 board：HTTP 400；上游异常：HTTP 500 `rank失败: ...`。', '读取平台榜单。合法 board 以 H.RANK_BOARDS 为准，索引示例 recommend/hot/new。'),
'api_latest': ('', '`{genre, name, mode, only_today, count, items}`；mode 区分今日上新/最新上架等。', '未知 genre：HTTP 400；HTTP 500 `latest失败: ...`。', '读取平台最新剧列表；refresh/no_cache 参与刷新选择。genre 常见 short_play/comic_series/ai_series。'),
'api_filters': ('', '`{genre, name, rows}`。', '未知 genre：HTTP 400；HTTP 500 `filters失败: ...`。', '读取平台分类筛选项。'),
'api_browse': ('', '`{genre, name, count, note, items}`；每条补 `stream_url` 和 `episodes_url`。', '未知 genre：HTTP 400；HTTP 500 `browse失败: ...`。', '读取平台筛选目录。theme/setting/background 可为逗号分隔文本，经本地 `_csv` 处理。'),
'api_episodes': ('', '`{meta, episodes}`，完整剧信息与每集模型，见 REQUEST_CHAIN。', 'HTTP 500 `episodes失败: ...`。', '读取 APP 剧详情/缓存。'),
'api_metrics_batch': ('`series_ids: list 或逗号分隔 str`；也兼容 `series_id`；必需得到非空 ID 集合，最多 200。`batch_size: 可转 int=20`，有效批大小限制 1–20。', '`{count, items, failed, batch_size}`。', '空 ID 或超过 200：HTTP 400；平台查询异常：HTTP 500 `metrics batch失败`。body 内类型不受 Pydantic 字段模型约束，转换失败可能成为 500。', '批量读取剧详情指标。'),
'api_play': ('', '`{series_id, title, note, episodes}`；集条目 `{index, vid, title, duration, encrypted_url, backup, size, definition, stream_url}`。note 明示 encrypted_url 是 CENC 密文地址。', 'HTTP 500 `play失败: ...`。', '查询详情与视频模型；ep 支持 all 或集数范围。返回可播放路径 `/stream?vid=...` 与远端密文 URL，不在本接口写媒体。'),
'api_download': ('', '`{task_id, status_url}`。', 'HTTP 500 `download失败: ...`。', '**即使是 GET 也会提交下载任务并写文件**；`ep` 支持 all/范围，`ep_covers` 控制集封面。'),
'api_download_status': ('', 'H.manager().status(task_id) 的透传结果；具体任务状态 schema 未在 handler 定义。', '未在 handler 显式捕获错误。', '只读任务状态。'),
'api_video_url': ('', '`{vid, url, backup, size, definition}`。', '没有 URL：HTTP 404 `无直链`；其它异常：HTTP 500 `video_url失败`。', '查询视频模型/缓存，URL 可能是加密媒体，不等于可直接播放文件。'),
'api_stream': ('', '`video/mp4` FileResponse；Content-Disposition inline，UTF-8 文件名。', '缺 series_id 和 vid：HTTP 400；找不到集号：HTTP 404；其它：HTTP 500 `stream失败`。', '**GET 会按需下载、生成解密缓存，再读本地文件**。vid 优先；否则用 series_id+ep；非数字 ep 回退第 1 集。'),
'dl_submit': ('`text: str=""`；`series_ids: list=[]`；`ranges: object={}`；`scores: object={}`；下载设置见公共 body 说明。', '成功 `{ok:true, settings}`；部分许可受限另加 `blocked, need_license, free_limit, free_used`；全部受限 `{ok:false, reason, blocked, free_limit, free_used}`。', '业务 JSON `{ok:false,error}`：queue is empty、已有下载运行；许可失败由 reason/blocked 表示。', '**启动后台下载/写文件**，清理 live 状态、取消标记，执行许可检查。'),
'dl_search': ('', '空 q：`{results:[]}`；正常 `{query, results, cursor, pending, backup, slow}` 并合并系列条带字段；分页 `{query,results,cursor,expired}`。', '过长搜索 `{query,results:[],error}`；无效游标 `expired:true`；异常 `{results:[],error}`，业务失败一般仍 HTTP 200。', '异步远端搜索、缓存及网页回退；again=1 表示重新询问任务。'),
'dl_search_seasons': ('', '`{series, related, complete, extra}`，可附 query、backup；具体条带字段来自 `_search_strip`。', '异常在上述结构附 `error`，complete=false；空/过长 q 返回空结果。', '查询/补全搜索关联续季信息。'),
'dl_rank': ('', '`{results,has_more:false,next_offset:0}`。', '异常同结构附 `error`。', '读取 ODL.hgdj_rank(category) 的网页榜单；category 仅 ai/human/comic，非法值回退 ai。**board/offset/size 虽声明但此 handler 不使用**。'),
'dl_rank_episodes': ('`series_ids: list=[]`；不是 list 则按空列表处理，最多传前 120 个。', '`{eps: ODL.hgdj_episodes(...) 的结果}`。', '异常 `{eps:{},error}`。', '读取网页集数信息。'),
'dl_preview': ('', '透传 ODL.hgdj_preview：成功 `{ok,series_id,title,episode_cnt,free,ep,url,poster,duration,width,height}`；具体字段随返回分支。', '`{ok:false,error}`，可为 network/unavailable/locked。', '只查询公开网页预览地址；受 accessible_episode_cnt 限制。fresh 被转为 bool。'),
'dl_explorer': ('', '`{results,page,pages,total,size}`。', '未显式捕获转换异常；内部目录不可用行为由 `_explorer_catalog` 决定。', '读取/缓存 explorer 目录，page 至少 1，size 1–60，默认 18。'),
'dl_episodes': ('', '`{series_id,title,cover,total,episodes}`，episodes 是排序去重的集序号，不是完整集对象。', '缺 ID `{episodes:[],error:"no series_id"}`；异常 `{episodes:[],error}`。', '查询剧详情/缓存。'),
'dl_resolve': ('`text: str=""`，分享链接或多行分享文本。', '`{resolved:[...]}`；成功条目 `{series_id,title,total,cover}`；busy 条目含 `error,busy`；不可用条目含 `hg_id,error,unavailable`；未识别含 `error:"unresolved"`。', '单个解析错误放在 resolved 条目；handler 自身未统一 catch。', '并发解析分享链接/榜单，最多 8 worker；可能访问远端网页。'),
'dl_status': ('', '没有 UI token 仅 `{running:bool}`。有 token 返回 `{running,started,mode,series,log}` 加速率/字节/活动数/集计数/settings/source；library 模式还含 phase/checked/to_check/found/unread/seasons。', '本接口是 UI token 豁免项，未授权不会收到完整日志/路径。', '只读任务与实时进度，部分异常回退快照。'),
'dl_signhealth': ('', '`{ok,fail}`，H.sign_stats()。', '无专门捕获分支。', '只读签名成功/失败计数。'),
'dl_signer_restarted': ('', '`{ok:true}`。', '无专门捕获分支。', '**改变签名器冷启动状态并启动后台预热**。此接口是“通知已重启”，不是直接杀进程。'),
'dl_diag': ('', '`{pid,web_port,bind_host,sign_server,signer_healthy,output_dir,output_writable,output_write_error,state_dir,data_dir,python,tls_trust,running,mode,app_log,dl_log}`。', '可写测试错误写入 output_write_error；签名测试异常写为不健康。', '**GET 也会创建输出目录、写入并删除 .hg_write_test、调用签名探测**；读取日志。'),
'dl_config_get': ('', '`{output_dir}`。', '无专门捕获分支。', '只读下载输出目录。'),
'dl_config_set': ('`output_dir: str=""`。', '成功 `{ok:true,output_dir}`。', '失败 `{ok:false,error,output_dir}`。', '**修改下载输出目录并持久化 dlconfig.json**。'),
'dl_open': ('', '`{ok:true,output_dir}`。', '`{ok:false,error,output_dir}`。', '**创建输出目录并打开系统文件管理器**。'),
'dl_bugreport': ('`logs: bool=true`，`screenshot: bool=false`，均经 bool()。', '`{ok:true,path,included}`，本地 bugreport ZIP。', '`{ok:false,error}`；截图失败可写入 ZIP 内 screenshot-FAILED.txt。', '**写日志 ZIP，可截图并打开文件管理器定位文件**；该 handler 没有自动上传报告。'),
'dl_pick': ('', 'Windows 原生目录选择器结果（通常 `{ok,path}`，其它错误键来自 `_pick_folder`）。', '非 Windows `{ok:false,error:"folder picker is Windows-only here — type the path instead"}`。', '**打开系统选目录对话框/子进程**；不自动提交配置。'),
'dl_library': ('', '`{items,root}`；item 含 `{name,series_id,title,local,total,new,fresh,score,updated,size,poster,cover,h264}`。底层证据 `offline_dl.dis.txt:18670`。', '扫描异常 `{items:[],error}`。', '**扫描本地下载库，seen_at 尚无有效值时可写入已看时间基线**；不发起媒体下载。'),
'dl_library_episodes': ('', '`{name,title,total,downloaded,fresh,episodes,h264}`；episodes 条目为 `{index,fresh}`。底层证据 `offline_dl.dis.txt:19081`（源行 2119、2132）。', '不安全/空目录名，或目录不存在：HTTP 404 `series not found`。', '只读本地剧目录。'),
'dl_library_seen': ('`names: list` 可批量；否则 `name: str=""`。', '批量 `{ok:true,count}`；单项 `{ok:bool}`。', '无效名不标记；未设置统一异常捕获。', '**持久化已看/已知状态**。'),
'dl_library_delete': ('`names: list=[]`，逐个名称清理/校验。', 'ODL.library_delete 结果，含 `{ok,moved,errors}`；moved 条目含恢复 token。', '异常 `{ok:false,moved:[],errors:{"*":错误}}`；如果移动结果不属于用户请求，自动恢复并记 `not the series asked for (left in place)`。', '**将所选库目录移入可恢复位置**；接口名 delete 不等于立即永久擦除。'),
'dl_library_restore': ('`token: str=""`，由 delete 返回。', '`{ok:true,name}`，透传 ODL.library_restore。底层证据 `offline_dl.dis.txt:19873`。', '`{ok:false,error}`：not in trash、已有同名剧目录、文件操作失败。', '**将 .trash 下之前移走的库目录恢复到输出根目录**。'),
'dl_library_merge': ('`name: str=""`；`variant: str="original"`，只允许 original/h264，否则回退 original。', '`{ok:true,started:true}`；进度另查 merge-status。', '无名称 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`。', '**后台合并剧集并写合并媒体**，状态含 variant。'),
'dl_library_merge_status': ('', '`{running,name,pct,file,error,done,variant}`，合并状态副本。', '无专门错误分支。', '只读。'),
'dl_library_convert': ('`names: list` 或 `name`；`keep_original: bool=true`；`mode: str="auto"`（auto/gpu/cpu）；`speed: str="quality"`（quality/balanced/fast）；`threads: 可转int=0`，限制 0–64。', '`{ok:true,started:true}`；进度另查 convert-status。', '无剧名 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`；无效 mode/speed 回退默认。', '**后台转码写 H264 文件**；keep_original 传入转换流程，涉及原文件保留策略。'),
'dl_library_convert_cancel': ('', '`{ok:true}`。', '异常 `{ok:false,error}`。', '**请求取消转码**。'),
'dl_library_convert_status': ('', '`{running,name,pct,encoder,mode,speed,total,series_done,converted,skipped,failed,error,done}`。', '无专门错误分支。', '只读转码状态。'),
'dl_poster': ('', '`image/jpeg` FileResponse，读取所选目录 poster.jpg，Cache-Control max-age=3600。', 'HTTP 404 `no poster`。', '只读本地海报。'),
'dl_library_open': ('`name: str=""`；`sub: str=""`（如 H264），经 `_safe_series_name` 校验。', '`{ok:true}`。', '`{ok:false,error}`：folder not found/no converted files yet/系统异常。', '**打开所选剧目录或子目录**。'),
'dl_library_play': ('`name: str=""`；`ep: 可转int/未提供=null`，内部从本地 MP4 文件名解析序号；省略、无法转 int 或未找到集号时，回退到按序号排序的第一个本地 MP4。', '`{ok:true,file}`。', '`{ok:false,error}`：folder not found/no episodes downloaded yet/系统异常。', '**在系统默认播放器打开本地集文件**；Windows startfile，macOS open，其它 xdg-open。'),
'dl_library_file': ('', '`video/mp4` FileResponse，Cache-Control no-store；优先找 第NNN集.mp4，随后按 MP4 文件名内数字匹配。', 'HTTP 404 `series not found` / `episode not found`。', '只读取所选库内媒体，安全名称校验。'),
'dl_library_update': ('`names: list/未提供`；下载设置见公共 body；未提供名称时可交底层进行库更新，明确给出的名称需合法。', '`{ok:true,settings}`。', '`{ok:false,error}`：invalid series name(s)、已有 download/update 运行。', '**后台检查库更新并下载缺集，写文件**，与主下载队列互斥。'),
'dl_library_seasons_decline': ('`series_ids: list=[]`，最多检查前 200 个，ID 必须匹配 15–20 位十进制。', '`{ok:true,declined}`。', '`{ok:false,error:"no series ids"}`。', '**记录拒绝的续季提示状态**。'),
'dl_cancel': ('', '`{ok:true}`。', '无专门错误分支。', '**设置取消下载标志**；日志说明完成已在途集，不再启动新集。'),
'dl_page': ('', '若 query `k` 与 HG_UI_TOKEN 匹配：303 跳转 `/dl` 并设置 token cookie；否则返回 web/downloader.html，Cache-Control no-store。', 'token 不匹配不会建立会话；页面可显示，受保护 API 仍拒绝。', '成功 bootstrap 时**设置 HttpOnly、SameSite=strict、path=/dl 的 UI cookie**。'),
'dl_license_status': ('', 'LIC.status() 透传对象；handler 未声明固定 schema（许可模块接口参见远端 API 文档）。', '未统一捕获 LIC.status 异常。', '读取许可状态，底层可能刷新缓存。'),
'dl_license_activate': ('`key: str=""`。', 'LIC.activate(key) 透传许可结果；字段由许可模块决定。', '失败 reason/错误由 LIC.activate 决定；handler 无统一 catch。', '**尝试激活许可并更新本机许可状态**。'),
'dl_license_deactivate': ('', 'LIC.deactivate() 透传结果。', '错误由许可模块决定。', '**解绑/停用本机许可**。'),
'dl_license_reactivate': ('', '有 current_key 时透传 LIC.activate(current_key)。', '无 key：`{ok:false,reason:"no_key"}`。', '**使用已保存 key 重新激活**。'),
'dl_license_usage': ('', 'LIC.usage() 透传统计；handler 未固定字段。', '错误由许可模块决定。', '读取许可用量。'),
'dl_license_plans': ('', '支付服务 GET /plans 的 JSON 透传，缓存 600 秒。', '`{plans:[],error:"unavailable"}`。', '网络读取方案/更新缓存。'),
'dl_license_buy': ('`plan: str=""`，只允许 month/year/life。', '`{ok:true,session_id,url}`。', '`{ok:false,reason}`：bad_plan/no_session/bad_checkout_url；网络失败另有 detail（截断 200 字）。', '**创建结账会话并打开浏览器支付页**；不是已完成付款。'),
'dl_license_purchase_poll': ('', 'pending 分支 `{pending:true,reason}`；拿到 key 后返回 `{pending:false,ok,activated,reason,usage}`。', '缺 session `{pending:false,ok:false,reason:"no_session"}`；网络 pending=true,reason=network；未就绪 reason=not_ready 或服务端 reason。', '**GET 若取回 key 会自动调用 LIC.activate**，并非严格只读。'),
'dl_license_manage': ('', '`{ok:true,url}`。', '`{ok:false,reason}`：no_key/unavailable/bad_portal_url；网络失败附 detail。', '**用当前 key/device 创建管理门户并打开浏览器**。'),
'dl_update_check': ('', '`{ok,current,latest,update,url,page,name,notes}`；失败/无可用结果 `{ok:false,current,update:false}`。', '网络等异常转上述失败结构；说明 notes 最多 800 字。', 'GET GitHub latest release，缓存 1800 秒；不下载安装包。'),
'dl_update_download': ('', '`{ok,path,name,sha256,signed,valid,publisher,expected_publisher,trusted}`。', 'busy `{ok:false,busy:true,error}`；无可信下载 URL/下载失败 `{ok:false,error}`。', '**下载 exe 到本地 update 目录、计算 SHA-256、调用 PowerShell Authenticode 检验**；仅允许预期 GitHub release 路径，不在此 handler 执行。'),
'dl_update_progress': ('', '`{ok:true,state,pct,downloaded,total,error}`。state 可 idle/starting/downloading/verifying/done/error。', '无专门错误分支。', '只读更新下载进度。'),
'dl_update_run': ('`path: str=""`，必须是本进程已下载记录对应 exe。', '`{ok:true}`。', '`{ok:false,error}`：unknown download、非 exe、无校验记录、SHA-256 改变、无法验签、预期发布者校验未通过。', '**经路径/记录/hash/发布者检查后使用 os.startfile 执行安装程序**。'),
}
assert set(spec)=={r['handler'] for r in routes}, (set(spec)^{r['handler'] for r in routes})

def auth(r):
    p=r['path']
    if p=='/dl': return 'UI bootstrap；不要求已有 UI token。'
    if p=='/dl/status': return 'UI token 可选；无 token 仅返回 running。'
    if p.startswith('/dl/'): return 'UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。'
    if p=='/img': return '不需 API key/UI token；仍受 Host/跨站和图片白名单限制。'
    if p=='/admin': return '页面本身不校验管理 token；安装版先被 404 隔离。'
    if p.startswith('/admin/') or p=='/stats': return 'ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。'
    if p in ('/','/ui'): return 'API key 豁免；安装版先被 404 隔离。'
    return 'API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。'

intro='''# 本地 HTTP API 文档

范围：本安装包 `app/server.pyc` 的 **70 个显式 FastAPI 路由**，不是仅从 GUI 的 fetch 字符串拼出的清单。请求签名器与远端平台接口另见总 API 文档及 [REQUEST_CHAIN.md](REQUEST_CHAIN.md)。本次仅静态读取，不调用下载、删除、许可、支付、更新执行等有副作用的接口。

对应可机器解析清单：[local-routes.json](evidence/local-routes.json)。提取器：[extract_local_routes.py](tools/extract_local_routes.py)。它用 xdis 读取字节码，解析顶层 app.get/post/delete 与 MAKE_FUNCTION 的默认值和注解，**不 import/exec 原程序**。每项附 handler 源行及 server.dis.txt 的物理行号。

## 运行地址、安装版可见性与鉴权

服务通常为 `http://127.0.0.1:<PORT>`；server 自身默认 8000，桌面启动器可选择其它端口。**静态注册不等于安装版可访问**：`_PACKAGED_BUILD = bool(LIC._PACKAGED)` 时，中间件仅放行 `/dl`、`/dl/*`、`/img`、`/favicon.ico`；其它路径直接 HTTP 404 `{detail:"not found"}`，早于后续 API key 检查。因此旧 `/search`、`/episodes`、`/video_url`、`/admin`、`/docs` 在打包模式均被隔离。证据 `server.dis.txt:802`、`:6795`（源行 661）。

公共检查按如下顺序执行：

1. 上述打包模式路径过滤。
2. 当 BIND_HOST 为留空/127.0.0.1/localhost 时，非空 Host 必须是 localhost 或 127.0.0.1（可带实际 PORT）；否则 HTTP 403 bad host。
3. `/dl*`、`/admin*`、`/img`、`/stats` 拒绝 Sec-Fetch-Site=cross-site 或非本机 Origin，返回 HTTP 403 cross-site request blocked。
4. 若配置 HG_UI_TOKEN，除了 `/dl` 和 `/dl/status`，`/dl*` 必须具有 cookie `hg_ui_<PORT>` 或 header `x-hg-token`，否则 HTTP 403 unauthorized (open the app window)。cookie 优先。
5. 非豁免、非 admin/stats 路径要求 header `x-api-key` 或 query `api_key`，无效 HTTP 401；每 key 每 60 秒默认 120 次，超过 HTTP 429（RATE_PER_MIN 可配置）。

管理员 API 由 handler 校验 header `x-admin-token` 或 query `admin_token` 与 ADMIN_TOKEN 相等且非空。`/admin` HTML 页面本身没有该校验。`/dl?k=<正确token>` 通过 303 跳转换取 path=/dl、HttpOnly、SameSite=strict cookie；`/dl/status` 不带有效 UI token 只暴露 `{running}`。签名服务 `X-Sign-Token` 与这些 UI/API/admin token 是四套不同用途的凭据。

证据：`server.dis.txt:6112`（UI token）、`:6175`（admin）、`:6232`（Origin）、`:6286`（Host）、`:6620`（跨站）、`:6698`（中间件）、`:23439`（UI cookie）。

## 参数、响应与错误约定

- 下文 Query 表完全来自函数注解与默认值。`必填` 与 `默认 null` 不同。`Request` 是框架注入，不是用户应传的参数。
- 所有正文入口都是 `payload: dict = Body(...)`：**JSON 对象 body 必填**，但没有为内部字段定义 Pydantic BaseModel。字段类型/默认值是 handler 的实际读取、转换与约定，不是额外 schema 强约束；未知字段通常不使用。
- Query/Body 的框架层缺失或类型错误通常是 HTTP 422。每条所列 error 是业务 handler 层；未捕获的底层异常可能 HTTP 500。大多数 `/dl/*` 业务失败仍返回 HTTP 200 + `ok:false`/`error`/`reason`，不要仅以 HTTP 200 判成功。
- 返回字段按实际条件分支列出，不承诺每次同时出现；透传底层对象明确标出未固定 schema，不臆造字段。
- 共同下载设置 body（`/dl/submit`、`/dl/library/update`）：`quality` 允许 1080p/720p/540p/480p/360p，默认或非法值回退 1080p；`series`（兼容 `series_at_once`）默认 2；`episodes`（兼容 `concurrency`）默认 4。两个并发量可转 int 且须在 1–16，bool/转换失败/越界回退各自默认；最后 episodes 不超过 `16 // series`。返回 settings 为 `{quality,series,episodes,workers,max_conn}`，workers=series×episodes、max_conn=16。证据 `server.dis.txt:10015`、`offline_dl.dis.txt:818`、`:2163`、`:43649`。
- **GET 不保证无副作用**：`/download` 提交下载、`/stream` 写媒体缓存、`/dl/diag` 写临时文件、`/dl/license/purchase-poll` 可激活许可，已逐项标注。

## 完整显式路由清单

'''
out=[intro,'| # | 方法 | 路径 | handler / 源行 | 安装版 |\n|---|---|---|---|---|\n']
for idx,r in enumerate(routes,1):
    allowed=r['path']=='/img' or r['path']=='/dl' or r['path'].startswith('/dl/')
    out.append(f"| {idx} | {r['method']} | `{r['path']}` | `{r['handler']}` / {r['source_line']} | {'按鉴权放行' if allowed else '404 隔离'} |\n")
out.append('\n## 逐项请求与响应\n\n')
for idx,r in enumerate(routes,1):
    body,result,error,effect=spec[r['handler']]
    out.append(f"### {idx}. {r['method']} `{r['path']}`\n\n")
    out.append(f"实现：`{r['handler']}`，原 `server.py:{r['source_line']}`；反汇编 [server.dis.txt:{r['disassembly_line']}](evidence/server.dis.txt#L{r['disassembly_line']})。\n\n")
    out.append(f"鉴权/可见性：{auth(r)}\n\n")
    params=[p for p in r['parameters'] if p['location']!='injected']
    if params:
        out.append('| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |\n|---|---|---|---|---|\n')
        for p in params:
            default='必填' if p['required'] else '`'+json.dumps(p['default'],ensure_ascii=False)+'`'
            validation=', '.join(f'{k}={v}' for k,v in p['validation'].items() if k!='description') or '—'
            out.append(f"| `{p['name']}` | {p['location']} | {p['type']} | {default} | {validation} |\n")
        out.append('\n')
    else:
        out.append('声明参数：无（Request 若存在由框架注入）。\n\n')
    if r['handler']=='dl_page': out.append('另从 request.query_params 读取 `k: str=""`，它不在函数签名中。\n\n')
    if body: out.append('Body 字段：'+body+'\n\n')
    out.append('返回：'+result+'\n\n错误：'+error+'\n\n行为/副作用：'+effect+'\n\n')
    r['auth']=auth(r)
    r['packaged_allowed']=r['path']=='/img' or r['path']=='/dl' or r['path'].startswith('/dl/')
    r['body_fields_note']=body
    r['response_note']=result
    r['error_note']=error
    r['side_effect_note']=effect

out.append('''## 框架自动路由与没有注册的路径

`server.py` 以 `FastAPI(title="红果短剧 API", version="1.0")` 初始化，未传 docs_url、redoc_url、openapi_url 开关（`server.dis.txt:956`）。已从安装器提取并校验 **FastAPI 0.141.1** 源码：其 [applications.py:1105](extracted/python/Lib/site-packages/fastapi/applications.py#L1105) setup 确定增加下列 4 条框架路径；[Starlette routing.py:224](extracted/python/Lib/site-packages/starlette/routing.py#L224) 的 Route 默认 GET 且追加 HEAD。因此是 **70 条显式 method/path + 8 条框架 method/path = 78 条组合**，框架路由机器表见 [framework-routes.json](evidence/framework-routes.json)。

| 方法 | 路径 | 请求参数 | 返回 | 非安装模式鉴权 | 副作用 |
|---|---|---|---|---|---|
| GET / HEAD | `/openapi.json` | 无业务参数，Request 注入 | OpenAPI JSON（HEAD 无 body） | API key 豁免 | 生成/缓存 schema |
| GET / HEAD | `/docs` | 无业务参数，Request 注入 | Swagger UI HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |
| GET / HEAD | `/docs/oauth2-redirect` | 框架 OAuth redirect 页面，参数由其 JS 使用，业务 server 未声明 | OAuth redirect HTML（HEAD 无 body） | **不在豁免清单，需 API key** | 浏览器 OAuth 回跳处理 |
| GET / HEAD | `/redoc` | 无业务参数，Request 注入 | ReDoc HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |

安装模式中，上述四条路径均先被过滤返回 404；非安装模式中的中间件错误（Host、401、429）仍按本文公共规则。HEAD 的自动补充仅在上述 Starlette Route 确认，不额外将 70 条 app.get 业务路由都臆计为支持 HEAD。

`/favicon.ico` 在中间件放行及 API key 豁免清单，但 **没有找到显式 handler 注册**；不要将其当作已实现的图片接口。没有发现本业务模块的动态 add_api_route/include_router/mount 追加路由。

## 与前端请求交叉核对及可复现性

提取的 `app/web/downloader.html`、`index.html`、`admin.html` 中页面请求用于交叉验证：桌面页使用 `/dl/*` 与 `/img`；旧页面使用 `/search`、`/rank`、`/latest`、`/filters`、`/browse`、`/episodes`、`/play`、`/download` 等；管理页面使用 `/admin/keys`、`/admin/keys/revoke`。证据 [index.html:59](extracted/app/web/index.html#L59)、[admin.html:47](extracted/app/web/admin.html#L47)、[downloader.inline.js:372](evidence/downloader.inline.js#L372)。外部 explorer 域名请求不应误计为本地注册路由。

该清单按程序声明完整覆盖 70 条 method+path 组合，`GET /admin/keys`、`POST /admin/keys`、`DELETE /admin/keys` 与 `GET/POST /dl/config` 分别计数。当前没有运行原 server，也没有通过调用写接口来猜返回值；需验证的动态环境行为与透传模块扩展字段均保留为明确边界。
''')
(ROOT/'analysis/LOCAL_API.md').write_text(''.join(out))
(ROOT/'analysis/evidence/local-routes.json').write_text(json.dumps(routes,ensure_ascii=False,indent=2)+'\n')
framework=[]
for path,handler,line in [('/openapi.json','openapi',1108),('/docs','swagger_ui_html',1123),('/docs/oauth2-redirect','swagger_ui_redirect',1141),('/redoc','redoc_html',1151)]:
    for method in ('GET','HEAD'):
        framework.append({'method':method,'path':path,'handler':handler,'source_line':line,'source':'fastapi/applications.py','classification':'framework','packaged_allowed':False,'auth':'api_key' if path.endswith('oauth2-redirect') else 'api_key_exempt','response_type':'application/json' if path=='/openapi.json' else 'text/html'})
(ROOT/'analysis/evidence/framework-routes.json').write_text(json.dumps(framework,ensure_ascii=False,indent=2)+'\n')
print('Rendered',len(routes),'route contracts')
