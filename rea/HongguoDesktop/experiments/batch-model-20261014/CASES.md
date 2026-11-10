# 实验逐请求索引

仅成功取得目标 VID 的视频轨道和 HTTP 下载地址才记作成功；没有下载媒体。

| 阶段 | 请求 | 设备摘要 | 结果 |
|---|---|---|---|
| 01-baseline | `our_original_batch` | `1d2f52d159` | 110001 |
| 01-baseline | `script_A_first` | `89bc882539` | 成功（5 档） |
| 01-baseline | `script_A_repeat` | `89bc882539` | 110001 |
| 01-baseline | `script_B_first` | `3d881e6c1d` | 成功（5 档） |
| 01-baseline | `our_original_single_control` | `1d2f52d159` | 成功（5 档） |
| 02-signature-crossover | `script_jar_first_jar` | `573a409776` | 110001 |
| 02-signature-crossover | `script_jar_first_python` | `573a409776` | 110001 |
| 02-signature-crossover | `script_python_first_python` | `81235be6e8` | 成功（5 档） |
| 02-signature-crossover | `script_python_first_jar` | `81235be6e8` | 110001 |
| 02-signature-crossover | `ours_jar_first_jar` | `c254f7d871` | 110001 |
| 02-signature-crossover | `ours_jar_first_python` | `c254f7d871` | 110001 |
| 02-signature-crossover | `ours_python_first_python` | `ef17e6c85d` | 成功（5 档） |
| 02-signature-crossover | `ours_python_first_jar` | `ef17e6c85d` | 110001 |
| 03-factors | `ours_python_16_first` | `b08e937572` | 成功（5 档） |
| 03-factors | `ours_python_16_repeat` | `b08e937572` | 110001 |
| 03-factors | `ours_python_curl_18_first` | `2f8369c1a6` | 成功（5 档） |
| 03-factors | `ours_jar_python_medusa_first` | `cfd8f7dbb7` | 110001 |
| 03-factors | `ours_jar_python_medusa_repeat` | `cfd8f7dbb7` | 110001 |
| 03-factors | `ours_python_jar_medusa_first` | `01138377f7` | 110001 |
| 03-factors | `ours_jar_python_argus_ladon_first` | `948f0b75ab` | 110001 |
| 03-factors | `ours_jar_no_medusa_helios_first` | `f726ec5a3d` | 110001 |
| 04-context-and-reuse | `jar_without_neptune_soter` | `c35d971d1c` | 110001 |
| 04-context-and-reuse | `python_with_jar_neptune_soter` | `d150056d79` | 成功（5 档） |
| 04-context-and-reuse | `jar_without_extras_with_python_medusa` | `9114a0ecb1` | 110001 |
| 04-context-and-reuse | `python_with_jar_gorgon` | `893d52e474` | 成功（5 档） |
| 04-context-and-reuse | `python_with_jar_helios` | `600553f67c` | 110001 |
| 04-context-and-reuse | `python_with_jar_argus_ladon` | `285454798f` | 成功（5 档） |
| 04-context-and-reuse | `python_stable_pid_launch_first` | `db69627a8b` | 成功（5 档） |
| 04-context-and-reuse | `python_stable_pid_launch_repeat` | `db69627a8b` | 110001 |
| 04-context-and-reuse | `script_baseline_A_after_interval` | `89bc882539` | 110001 |
| 04-context-and-reuse | `python_original_stored_ids` | `1d2f52d159` | 成功（5 档） |
| 04-context-and-reuse | `python_fresh_end_control` | `8f51c79a37` | 成功（5 档） |
| 04-context-and-reuse | `our_original_single_end_control` | `1d2f52d159` | 成功（5 档） |
| 05-helios-medusa-pair | `jar_with_python_hm_A_first` | `cf93d85941` | 成功（5 档） |
| 05-helios-medusa-pair | `jar_with_python_hm_A_repeat` | `cf93d85941` | 110001 |
| 05-helios-medusa-pair | `jar_with_python_hm_B_first` | `dc07dfbeca` | 成功（5 档） |
| 05-helios-medusa-pair | `python_original_stored_ids_revisit` | `1d2f52d159` | 成功（5 档） |
| 05-helios-medusa-pair | `jar_original_stored_ids_end_control` | `1d2f52d159` | 110001 |
| 05-helios-medusa-pair | `python_fresh_end_control` | `ae840bd9c9` | 成功（5 档） |
| 06-stored-identity-repeat | `python_stored_first` | `1d2f52d159` | 成功（5 档） |
| 06-stored-identity-repeat | `python_stored_repeat` | `1d2f52d159` | 成功（5 档） |
| 06-stored-identity-repeat | `jar_python_hm_stored_first` | `1d2f52d159` | 成功（5 档） |
| 06-stored-identity-repeat | `jar_python_hm_stored_repeat` | `1d2f52d159` | 成功（5 档） |
| 06-stored-identity-repeat | `python_stored_curl` | `1d2f52d159` | 成功（5 档） |
| 06-stored-identity-repeat | `jar_stored_single_final_control` | `1d2f52d159` | 成功（5 档） |
