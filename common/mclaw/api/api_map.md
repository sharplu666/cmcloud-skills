# API Map

mclaw/api 已注册 API 的快速索引（联邦式 Service：`<namespace>.<leaf>` dotted 全名）。
新增 API 时必须同步追加一行（见 `how_to_add_api.md` 步骤 6）。

## search_fusion

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `search_fusion.search_merge_file` | `POST /richlifeApp/aiService/api/text/intelligent/search/merge/file` | `mclaw/api/search_fusion/search_merge_file_api.py` |
| `search_fusion.search_merge_image` | `POST /richlifeApp/aiService/api/text/intelligent/search/merge/image` | `mclaw/api/search_fusion/search_merge_image_api.py` |
| `search_fusion.search_face_recognize` | `POST /richlifeApp/api/text/intelligent/search/face/recognize` | `mclaw/api/search_fusion/search_face_recognize_api.py` |
| `search_fusion.search_by_fileId` | `POST /richlifeApp/aiService/api/text/intelligent/search/merge/image/aiAnalysisInfo`（**同步**） | `mclaw/api/search_fusion/search_by_fileId.py` |

## operation

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `operation.batch_move_files` | `POST /richlifeApp/personalSaas/file/batchMoveAsync`（异步，轮询 `/richlifeApp/personalSaas/task/get`） | `mclaw/api/operation/batch_move_files_api.py` |
| `operation.submit_photo_organize_task` | `POST /richlifeApp/api/openclaw/photoOrganize/task`（**multipart/form-data**，同步返回 taskId） | `mclaw/api/operation/photo_organize_submit_api.py` |
| `operation.query_photo_organize_task` | `POST /richlifeApp/api/openclaw/photoOrganize/task/query`（**同步**，返回 `taskInfo` + `results`） | `mclaw/api/operation/photo_organize_query_api.py` |
| `operation.retry_photo_organize_task` | `POST /richlifeApp/api/openclaw/photoOrganize/task/retry`（**同步**，对失败/部分失败任务重试，仅处理失败文件） | `mclaw/api/operation/photo_organize_retry_api.py` |
| `operation.resolve_session_folder_name` | `POST /richlifeApp/api/openclaw/session/folder/name`（**同步**，返回 `folderName` + `folderId`） | `mclaw/api/operation/session_folder_name_api.py` |

## search

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `search.get_async_task_status` | `POST /richlifeApp/personalSaas/task/get` | `mclaw/api/search/get_async_task_status_api.py` |
| `search.reading_record_list` | `POST /richlifeApp/bookshelf/readingRecord/list`（**同步**） | `mclaw/api/search/reading_record_list_api.py` |

## image_tool

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `image_tool.ai_avatar` | `POST /richlifeApp/aiService/api/image/avatar/cartoon`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/ai_avatar_api.py` |
| `image_tool.ai_expand_image` | `POST /richlifeApp/aiService/api/image/expand`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/ai_expand_image_api.py` |
| `image_tool.ai_image_generate` | `POST /richlifeApp/aiService/api/image/generate`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/ai_image_generate_api.py` |
| `image_tool.ai_retouch` | `POST /richlifeApp/aiService/api/image/beautify/face`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/ai_retouch_api.py` |
| `image_tool.baby_face_prediction` | `POST /richlifeApp/aiService/api/image/edit/gabyGrowthPrediction`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/baby_face_prediction_api.py` |
| `image_tool.baby_time_machine` | `POST /richlifeApp/aiService/api/image/edit/babyTimeMachine`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/baby_time_machine_api.py` |
| `image_tool.human_matting` | `POST /richlifeApp/aiService/api/image/edit/imageCutout`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/human_matting_api.py` |
| `image_tool.image_caption` | `POST /richlifeApp/aiService/api/image/caption`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/image_caption_api.py` |
| `image_tool.image_comic_style` | `POST /richlifeApp/aiService/api/image/edit/faceAnime`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/image_comic_style_api.py` |
| `image_tool.image_enhance` | `POST /richlifeApp/aiService/api/image/quality/repair`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/image_enhance_api.py` |
| `image_tool.image_shift` | `POST /richlifeApp/aiService/api/image/edit/shift`（**同步**） | `mclaw/api/image_tool/image_shift_api.py` |
| `image_tool.live_photo` | `POST /richlifeApp/aiService/api/image/alivePhoto`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/live_photo_api.py` |
| `image_tool.old_photo_restore` | `POST /richlifeApp/aiService/api/image/restore/oldPhoto`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/old_photo_restore_api.py` |
| `image_tool.text_to_image` | `POST /richlifeApp/aiService/api/image/textToImage`（异步，轮询 `/richlifeApp/aiService/api/async/task/result`） | `mclaw/api/image_tool/text_to_image_api.py` |

## personal_saas

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `personal_saas.batch_get` | `POST /richlifeApp/personalSaas/file/batchGet`（**同步**） | `mclaw/api/personal_saas/batch_get_api.py` |
| `personal_saas.batch_check_exists` | `POST /richlifeApp/personalSaas/file/batchCheckExists`（**同步**） | `mclaw/api/personal_saas/batch_check_exists_api.py` |
| `personal_saas.batch_get_download_url` | `POST /richlifeApp/personalSaas/file/batchGetDownloadUrl`（**同步**） | `mclaw/api/personal_saas/batch_get_download_url_api.py` |
| `personal_saas.file_create` | `POST /richlifeApp/personalSaas/file/create`（**同步**） | `mclaw/api/personal_saas/file_create_api.py` |
| `personal_saas.file_complete` | `POST /richlifeApp/personalSaas/file/complete`（**同步**） | `mclaw/api/personal_saas/file_complete_api.py` |
| `personal_saas.create_folder` | `POST /richlifeApp/personalSaas/file/createFolder`（**同步**） | `mclaw/api/personal_saas/create_folder_api.py` |
| `personal_saas.batch_update` | `POST /richlifeApp/personalSaas/file/batchUpdate`（**同步**） | `mclaw/api/personal_saas/batch_update_api.py` |
| `personal_saas.query_file_schedules` | `POST /richlifeApp/personalDynamic/queryFileSchedules`（**同步**） | `mclaw/api/personal_saas/query_file_schedules_api.py` |
| `personal_saas.query_personal_dynamic` | `POST /richlifeApp/personalDynamic/queryPersonalDynamic`（**同步**，legacy：转存动态 5/6/7） | `mclaw/api/personal_saas/query_personal_dynamic_api.py` |
| `personal_saas.video_preview` | `POST /richlifeApp/personalSaas/videoPreview/getPreviewInfo`（**同步**） | `mclaw/api/personal_saas/video_preview_api.py` |
| `personal_saas.batch_copy` | `POST /richlifeApp/personalSaas/file/batchCopy`（异步，轮询 `/richlifeApp/personalSaas/task/get`） | `mclaw/api/personal_saas/batch_copy_api.py` |
| `personal_saas.get_path` | `POST /richlifeApp/personalSaas/file/batchGetPath`（**同步**） | `mclaw/api/personal_saas/get_path_api.py` |

## album

| dotted registry 名 | 接口路径 | 调用脚本 |
|---------------------|---------|----------|
| `album.image_deduplicate` | `POST /richlifeApp/aiService/api/image/deduplicate`（**同步**） | `mclaw/api/album/image_deduplicate_api.py` |
| `album.image_batch_deduplicate_submit` | `POST /richlifeApp/api/openclaw/deduplicate/submit`（**multipart/form-data**，同步返回 taskId） | `mclaw/api/album/image_batch_deduplicate_api.py` |
| `album.image_batch_deduplicate_result` | `POST /richlifeApp/api/openclaw/deduplicate/result`（**同步**，返回任务状态/统计/结果文件 `respUrl`，轮询由调用方控制） | `mclaw/api/album/image_batch_deduplicate_api.py` |
| `album.select_photo_submit` | `POST /richlifeApp/api/image/asyncSelectPhoto`（**multipart/form-data**，同步返回 taskId；`imageIdFile` 每行 `{"fileId","score"}`） | `mclaw/api/album/select_image_api.py` |
| `album.select_photo_result` | `POST /richlifeApp/api/image/selectPhotoResult`（**同步**，status 1-5；成功时内存直读 `resultUrl` 解析 good/bad 并随终态日志打印，轮询由调用方控制） | `mclaw/api/album/select_image_api.py` |
| `album.classify_addr_list` | `POST /richlifeApp/personalSaas/album/classify/addr/list`（**同步**） | `mclaw/api/album/classify_addr_list_api.py` |
| `album.classify_addr_file_list` | `POST /richlifeApp/personalSaas/album/classify/addr/file/list`（**同步**） | `mclaw/api/album/classify_addr_file_list_api.py` |
| `album.classify_person_list` | `POST /richlifeApp/personalSaas/album/classify/person/list`（**同步**） | `mclaw/api/album/classify_person_list_api.py` |
| `album.classify_person_file_list` | `POST /richlifeApp/personalSaas/album/classify/person/file/list`（**同步**） | `mclaw/api/album/classify_person_file_list_api.py` |
| `album.classify_thing_list` | `POST /richlifeApp/personalSaas/album/classify/thing/list`（**同步**） | `mclaw/api/album/classify_thing_list_api.py` |
| `album.classify_thing_file_list` | `POST /richlifeApp/personalSaas/album/classify/thing/file/list`（**同步**） | `mclaw/api/album/classify_thing_file_list_api.py` |
| `album.photo_customization_list` | `POST /richlifeApp/personalSaas/album/photo/customization/list`（**同步**） | `mclaw/api/album/photo_customization_list_api.py` |
| `album.photo_customization_file_list` | `POST /richlifeApp/personalSaas/album/photo/customization/file/list`（**同步**） | `mclaw/api/album/photo_customization_file_list_api.py` |
| `album.photo_customization_add` | `POST /richlifeApp/personalSaas/album/photo/customization/add`（**同步**） | `mclaw/api/album/photo_customization_add_api.py` |
| `album.photo_customization_file_add` | `POST /richlifeApp/personalSaas/album/photo/customization/file/add`（**同步**） | `mclaw/api/album/photo_customization_file_add_api.py` |
| `album.photo_customization_update` | `POST /richlifeApp/personalSaas/album/photo/customization/update`（**同步**） | `mclaw/api/album/photo_customization_update_api.py` |
| `album.story_memory_list` | `POST /richlifeApp/personalSaas/album/story/memory/list`（**同步**） | `mclaw/api/album/story_memory_list_api.py` |
| `album.story_memory_file_list` | `POST /richlifeApp/personalSaas/album/story/memory/file/list`（**同步**） | `mclaw/api/album/story_memory_file_list_api.py` |
| `album.story_memory_add` | `POST /richlifeApp/personalSaas/album/story/memory/add`（**同步**） | `mclaw/api/album/story_memory_add_api.py` |
| `album.story_memory_update` | `POST /richlifeApp/personalSaas/album/story/memory/update`（**同步**） | `mclaw/api/album/story_memory_update_api.py` |
| `album.story_memory_playlist_add` | `POST /richlifeApp/personalSaas/album/story/memory/playlist/add`（**同步**） | `mclaw/api/album/story_memory_playlist_add_api.py` |
| `album.album_share_get_info` | `POST /richlifeApp/personalSaas/album/share/getAlbumShareInfo`（**同步**；鉴权头 `get_album_share_header`，含 `x-DeviceInfo`） | `mclaw/api/album/album_share_get_info_api.py` |
| `album.search_ai_story` | `POST /richlifeApp/search/SearchAIStory`（**同步**） | `mclaw/api/album/search_ai_story_api.py` |

