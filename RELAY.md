# 转播实播核录

主控负责编排声音和复听，播出端跟随外部帧钟。两端使用各自的 SQLite 库，通过回环 HTTP 交接。对同一场转播，两端重开时各自使用原库。普通场次的准备、触发、叫停、出帧和复听沿用 README.md；转播场次的触发与叫停也沿用原入口，场务侧以主控已核录的前沿使用原有接纳规则。播出端每次成功接受帧钟脉冲所得的固定双路输出，即本地工单的实播。

## 入口

转播功能完成后用下列命令分别起播出端和主控。`--relay` 可重复，值为 `场次=播出端基址`。名单在启动时配置，转播从帧 0 起办。两个进程都只监听 `127.0.0.1`，接受 `--host 127.0.0.1` 和 `--port`。传 `--port 0` 时，从启动输出的 `127.0.0.1:<实际端口>` 取得地址。两端的 `GET /ready` 成功返回 200 和 `{"ready":true}`。

```sh
python3 -B -m playout.http --db playout.sqlite --show early --show late --port 8766
python3 -B -m mix.http --db studio.sqlite --show studio --show early --show late --relay early=http://127.0.0.1:8766 --relay late=http://127.0.0.1:8766 --port 8765
```

JSON 正文、场次路径编码和帧号沿用 README.md。`request_id` 是有效 UTF-8 的非空白字符串，身份按场次、帧号和请求号共同区分。两端实际传递候选和取证的内部 HTTP 入口可随实现确定，只有播出端的 `tick` 推进其帧钟。

| 服务及请求 | 成功响应 |
| --- | --- |
| 主控 `POST /shows/{show}/stage`，正文 `{"frame":0,"request_id":"opening-0"}` | `{"show":"early","frame":0,"request_id":"opening-0","status":"accepted"}`。已过帧且该请求未被接纳时 `status` 为 `expired`。两种结果均为 200。无法确定播出端的决定时返回 202 和同一结构，`status` 为 `pending`。 |
| 播出端 `POST /shows/{show}/tick`，正文 `{"frame":0}` | 200，返回 `{show,frame,left,right,request_id}`。节目取首接纳候选的双路值和请求号，补静音返回左右各 0、`request_id` 为 `null`。 |
| 主控 `POST /shows/{show}/sync`，空正文或 `{}` | 200，返回 `{show,last_frame}`，`last_frame` 是主控最后已核录帧，初始为 -1。 |
| 主控 `GET /shows/{show}/frames/{frame}` 与 `GET /shows/{show}/replay?start=0&end=1` | 保留原查帧和复听响应。转播场次的正式帧及 `frames` 中的每一帧增加 `request_id`。 |

`stage` 的候选按原双路混音和限幅口径，从该逻辑请求处理期间的一致节目视图取得。已接纳节目即使恰好为双路零值，也保留实际请求号。已经接纳的请求按原场次、帧号和请求号重投时，始终返回原接纳结果，即使对应帧已经实播、节目触发已改变或任一端已经重开。初次接纳限于播出端下一待播帧。未来帧候选和未来帧脉冲报 409 `not_next_frame`。本帧接纳首个请求后，另一个请求号来抢同一待播帧报 409 `candidate_exists`。已经落下的帧重复 `tick` 返回原结果。

核录从已有前沿续接，当次可取得的连续实播结果按原帧号落档。并发新增的实播可在下次同步续接。本次新增的正式记录与主控前沿在一次提交中生效。读取播出结果或本地主控提交失败时保留上次正式记录和前沿，解除故障后可重试。尚未核录的单帧或含此类帧的复听区间沿用 404 `frame_not_aired`。已准备的普通场次调用 `stage` 或 `sync` 返回 409 `not_relay_show`，转播场次调用旧 `POST /shows/{show}/frames` 返回 409 `relay_required`。非法正文、未知场次和 SQLite 写入失败沿用原错误结构及 400、404、503 约定，`sync` 取证失败也用 503。

## 转播工单

在 `early` 和 `late` 各发布右路延时 2 的场景，将同一素材 A=8 触发到左路第 0 帧。`early` 先交候选 `opening-0` 再落帧，应得到 `(8,0)` 和 `opening-0`。`late` 先落帧再交相同编号的候选，应得到 `(0,0)` 和空请求号，后到的候选报 `expired`。留空两场的第 1 帧，即使先前有迟件，第 1 帧也仍补静音。核录前按原接口查第 0 帧报未播，核录后按原序复听第 0、1 帧。

丢掉 `early` 的候选接纳回包和第 0 帧的实播回包。关掉主控，让播出端继续落第 1 帧。重开两端后叫停原触发，重新提交第 0 帧原请求和第 0 帧脉冲，继续得到原接纳结果和 `(8,0)`。连续核录应到达帧 1，再核录仍为帧 1。可沿用原正式出帧测试的提交失败手法，检验核录失败时档案和前沿一起保留、播出端的实播仍可重取、解除失败后核录得到相同值。

`relay_fixture.py` 的 `running_endpoint` 可用独立库文件启动、关闭、重开端点，`forwarding` 提供回环转发。对一个方法及可选精确路径调用 `intercept_once`，可先等待 `arrived` 再放行，或在上游已返回后丢弃回包。`finished` 与 `upstream_status` 供核验上游是否已作答。夹具的独立运行用原素材接口检查这些能力。

`.pointwise-runtime.json` 已登记普通场次的启动和就绪地址。交付时让 `verify` 运行原回归和转播请求链核验，断言失败须非零退出。`demo` 实际走一遍断联前后转播并展示播出值及按原号复听的结果。命令继续用参数数组登记。原测试和 V1 演示可直接重跑。
