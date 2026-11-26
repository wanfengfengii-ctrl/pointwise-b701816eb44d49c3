# 广播剧直播音效服务

小型广播剧制作室用这个本地服务登记音效、切换回声场景、按演出提示触发或叫停，再按帧播出和复听。服务使用 Python 3.11 标准库、回环 HTTP 和 SQLite。帧号是由播出员推进的本地整数帧钟。

## 运行

```text
python3 -B -m mix.http --db studio.sqlite --show studio --port 8765
python3 -B -m mix.http --db studio.sqlite --show studio --init-only
python3 -B check_project.py
python3 -B demo.py
```

第一条监听 `127.0.0.1`，第二条只准备库和场次。可重复传入 `--show` 准备多场，各自拥有场景和帧前沿。初次准备把前沿设为 0，重复执行保留所有已提交状态。回归入口由平台提供，完整测试在 `tests` 包，直接调用 `python3 -B -m unittest discover` 也可运行。演示使用独立临时空库和本地 HTTP 请求，核对正式帧及复听，断言失败时以非零状态退出。

## HTTP 接口

POST 的字段为固定集合，正文采用 UTF-8 JSON。`show` 是准备时指定的名称，路径中需要转义的字符使用 URL 百分号编码。资产版本号和触发号为正整数。URL 中的整数参数采用十进制数字。输出名为 `left` 或 `right`。请求正文上限为 65536 字节，整数文本使用 Python 3.11 的解析范围。素材、延时和帧号在受理、计算和持久化时保持整数精度。

| 方法和路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `POST /assets` | `{"name":"A","sample":8}` | 201，`version`、`name`、`sample` |
| `GET /assets/{version}` | 路径中的版本号 | 200，该版本的 `version`、`name`、`sample` |
| `POST /shows/{show}/scenes` | `{"revision":"opening","echo_output":"left","echo_delay":2}` | 201，`show`、`revision`、`echo_output`、`echo_delay` |
| `POST /shows/{show}/cues` | `{"asset_version":1,"dry_frame":0,"dry_output":"left"}` | 201，`cue_id` |
| `POST /shows/{show}/cues/{cue_id}/stop` | 空正文或 `{}` | 200，`cue_id`、`stopped: true` |
| `POST /shows/{show}/frames` | `{"frame":0}` | 201，`show`、`frame`、`left`、`right` |
| `GET /shows/{show}/frames/{frame}` | 路径中的帧号 | 200，同一正式帧结构 |
| `GET /shows/{show}/replay?start=0&end=3` | 首尾帧，均包含 | 200，`frames` 数组，按帧号数值升序 |

JSON 错误响应包含 `error` 和 `message`。非法正文、字段、帧号或区间用 400，正文超限用 413。未知场次、版本或本场不存在的触发，以及缺少正式帧，分别用 404 `unknown_show`、`unknown_asset`、`unknown_cue`、`frame_not_aired`。未开场接纳、重复提交同名场景修订、原声帧已播或出帧号与前沿不符，分别用 409 `show_not_open`、`revision_exists`、`dry_frame_aired`、`not_next_frame`。SQLite 事务失败用 503 `storage_failure`。出帧写入失败时可以重试原帧号。复听区间有任何一帧待播时，整个请求返回 `frame_not_aired`。

## 当天播出

1. 素材员登记 A=8、B=6，再按版本试听。重录同名素材时旧版本仍能按原号试听。
2. 导演为 `studio` 发布左路回声、延时 2 的首修订，场次开场。后续修订被批准时立即生效并留下历史。
3. 场务使用 A 的精确版本，接纳左路帧 0 的触发。播出员正式提交帧 0，得到 `(8,0)`。
4. 导演切换至右路回声、延时 1。场务把 B 触发到左路帧 2。已接纳的 A 回声仍在左路帧 2，B 的回声在右路帧 3。
5. 播出员顺序播帧。帧 1 为 `(0,0)`。A 仍有效时帧 2 为 `(10,0)`。如果场务在帧 2 提交前叫停 A，帧 2 为 `(6,0)`。两支帧 3 都为 `(0,6)`。
6. 播出员回查帧 0 并复听整段。帧 2 若先正式提交，再按 A 号叫停，帧 2 仍为 `(10,0)`。

单次触发产生一份原声和一份回声，二者取素材的原样本。回声落点为原声帧加接纳时的正整数延时。布尔值、小数、空值与字符串不能作样本或延时，零样本可以登记。每路按帧精确求有符号整数和，最后限幅到 −10 至 10，空路输出 0。例如同路同帧的 +8、+6、−6 输出 8。重复使用一个素材版本的不同触发分别获得触发号，重复叫停同一有效引用仍报告已叫停。

场景发布、接纳、叫停和出帧依据服务提交顺序。`cues/accept.py` 保存接纳时的播放义务，`mix/emit.py` 用同一个写事务结算有效分量、追加正式帧并推进前沿。正式响应在提交成功后发送，`aircheck` 只读取已提交的记录。静音帧也有正式记录。帧号、场景修订和触发号可用于重复核对当天的播出结果。
