# Local Docker 蓝绿流量路由设计（T21.6.3.5）

> **状态：T21.6.3.5.2.10–.2.11 已于 2026-11-17 通过真实 Docker Engine CI #762。** HAProxy 3.4.7 pinned image/immutable identity、HAProxy `-c`、Host 0700/0600 state、scope bridge、Router container create/inspect、Runtime API `show info`、`show map` 定位 `#0`、`get map #0 active = none` 和 immutable-ID cleanup 均有真实运行证据；结构化 artifact `14294272313` 报告 `status=ready`、`cleanup=removed`。**此证据只证明 Router bootstrap 与初始空路由 read-back，不证明 app routed deployment、active-slot 切换、流量转发、drain/retire 或 rollback；Local Docker 安全替换和 zero-downtime rollback 仍 unsupported。**  
> 日期：2026-11-15；范围：单机 Docker Engine、单个 project/environment scope。

## 1. 问题与目标

当前 LocalDockerProvider.deploy() 直接将应用容器 publish 到 host port。旧实例占有 host port 时，候选实例不能绑定同一端口。因此“启动候选 → stop 旧容器”不是蓝绿切换，也没有可验证的流量读回。

设计新增 Host-owned traffic router：
- 每个 project/environment 一个持久 Router 容器和独立 user-defined bridge network。
- 应用容器只加入 scope network，不 publish host ports；Router 是唯一发布 host ports 的容器。
- candidate 在旧实例继续运行时启动，不争抢 host ports。
- 所有端口共用一个 active-slot 指针；一次路由切换改变整个 scope 的所有端口。
- Runtime API read-back 与 Router ID、应用 immutable container ID、network address 和 journal 交叉验证。

**v1 仅支持 TCP mappings。UDP、host networking、Windows containers、跨 Docker daemon 和云 provider 返回 unsupported。** TCP passthrough 可承载 HTTP、HTTPS/TLS passthrough 和普通 TCP；v1 不做 TLS 终止、HTTP path 或 Host header 路由。

## 2. 选型：HAProxy OSS + Runtime API

选择 HAProxy 是因为 Runtime API 支持在线更新 server 地址/端口及 ready、drain、maint 状态，也能读取 server state/statistics/connections；单条 set map 可原子更新单个 route selector，多条 map 更新可用 prepare map / commit map 原子提交。[set server](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-server/) · [show servers state](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-state/) · [show stat](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-stat/) · [set map](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-map/) · [prepare map](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/prepare-map/) · [commit map](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/commit-map/)

Router 只开放 Unix stats socket（mode 600, level admin），不发布 admin TCP port。Host 通过固定 argv 的 docker exec -i + socat 连接；Docker runner 通过 subprocess.run(input=..., shell=False) 传入有界 stdin，不使用 shell 管道。Runtime API 命令由严格校验过的 slot/server/map/IP/port builder 生成，NUL 与超限输入在 Docker 调用前拒绝。[HAProxy Unix socket management](https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/management/)

Runtime API 的改动保存在运行进程内存，不会自动写回配置文件/磁盘；Host 因此必须同时持久化 route map 文件，并在 Router 重启后比对“文件期望值”与“运行时已加载值”。[HAProxy Runtime API](https://www.haproxy.com/documentation/haproxy-runtime-api/)

## 3. Docker 拓扑与端口契约

    Host published ports
             |
             v
    +------------------------------------+
    | HAProxy Router (one per scope)     |
    | Unix admin socket; no TCP admin   |
    | frontend 8080 -> backend slot_a/b |
    | frontend 8443 -> backend slot_a/b |
    +------------------+-----------------+
                       |
             user-defined bridge network
                       |
             +---------+---------+
             |                   |
       previous app         candidate app
       full ID=P            full ID=C
       private IP           private IP
       no published ports   no published ports

Docker user-defined bridge 支持网络内容器名/alias 互访，并提供明确的网络边界；不使用默认 bridge 的 legacy --link。[Docker networking](https://docs.docker.com/engine/network/) · [Docker bridge driver](https://docs.docker.com/engine/network/drivers/bridge/)

输入沿用 host:container[/tcp|udp]：
- host ports 只由 Router 发布；应用容器不传 --publish。
- 每个 host port 对应一个 HAProxy frontend/backend。
- 所有 backend 共用 active-slot map entry（active_slot → slot_a|slot_b）。
- 每个 backend 预定义 slot_a/slot_b；Host 通过 Runtime API 更新槽位 IP/port。
- UDP、重复 host port、冲突、无效映射在 side effect 前拒绝；不得退化为 direct publish。

## 4. 原子路由模型

### 4.1 一个 selector 驱动所有端口，并且不得隐式回退

每个 TCP backend 定义两个 server slots，HAProxy 用同一个 active-slot map key 产生 ACL，再通过 use-server 明确指定 slot。use-server 支持 TCP mode；但如果规则指定的 server 为 DOWN，HAProxy 在没有 persist/force-persist 时会忽略该规则并继续后续选择。因此 Router config 必须同时满足：

- slot_a 与 slot_b server 均配置 weight 0；不能存在任何可绕过 selector 的普通 load-balancing fallback。
- 每个 frontend/backend 只使用同一 active-slot map key；active-slot 缺失/非法、两个 use-server 规则都不匹配或目标 server DOWN 时，连接应失败，而不是落到另一个槽位。
- 不配置 cookie、stick-table、source persistence 或 force-persist；每条新连接都严格使用当前 active-slot selector。
- map 缺失/解析失败、Runtime API read-back 与预期 selector 不一致、目标 backend 非 UP 时，Host 将 route 标记为 unverified/needs_reconciliation，不接受“HAProxy 仍能转发”作为成功证据。

所有 frontend 查询相同 active-slot map key，因此多端口不需要逐个切换。一次 set map <map-id> active_slot slot_b 是唯一 route switch；不得循环改端口并声称整个 scope 原子切换。[HAProxy use-server（支持 TCP mode，且规则按顺序评估）](https://docs.haproxy.org/3.4/configuration.html)

### 4.2 Candidate preparation

1. 持久化 replacement journal：operation ID、previous/candidate deployment ID、immutable runtime ID、Router ID、slot、route generation。
2. 确认 Router 和 app 位于 scope network。
3. 以不可变 image digest 启动 candidate，不发布 host ports；inspect 完整容器，验证 Docker ID == journal ID。
4. 读取 network IP 和各 container port；只有 immutable ID 完全匹配后才信任 IP。
5. Docker HEALTHCHECK 必须 fresh healthy；缺少 HEALTHCHECK 保持 unknown。
6. 将 candidate IP/port 写入 inactive slot，启用 HAProxy TCP health check；所有 candidate backend 必须 UP，且 Docker health 仍 healthy。

### 4.3 Switch intent 与 route commit

当前 journal 需新增 traffic_switch_pending phase：
1. CAS journal 到 traffic_switch_pending，持久化 route generation、Router ID、old/new slot。
2. 将 candidate active-slot map 写入 Host 私有目录；临时文件 + 原子 rename + fsync 文件和目录。
3. 更新 candidate slot 地址/状态；逐端口核对 IP/port 和 HAProxy health。
4. 执行单条 set map 更新 active_slot。这是全 scope 唯一切换点。
5. Runtime API read-back：get/show map 验证 active slot；show servers state/show stat 验证每个 backend 的候选地址、端口和 UP 状态；从 show stat 的 server rows 读取 scur（当前 session 数）用于 drain 观察；与 Router ID、candidate Docker immutable ID 和 network IP 交叉核验。show servers conn 仅用于诊断，不作为自动 retirement 的计数依据。
6. 全部读回匹配后，journal 才能进入 traffic_switched，active pointer 才能 CAS 更新。

API 超时/错误不能凭命令返回值猜测切换结果；必须 read-back。确认指向 old/candidate 才能报告 observed route；unknown、地址不匹配、Router ID 不符、backend 缺项一律 needs_reconciliation，并保留两实例与 scope reservation。

### 4.4 Drain previous

route 指向 candidate 且 read-back 成功后，将 old slot 设为 drain；但 HAProxy 的 drain 状态仍允许新的 persistent connections，因此它不能单独证明已停止接收全部新连接。Router v1 不配置 persistence，且所有新连接必须通过 active-slot map 的 use-server 规则；active selector 改变后，old slot 不再是新连接的目标。Host 用 show stat 每个 old server row 的 scur（当前 session 数）做有界轮询，并要求连续多个采样为零；show servers conn 官方定位为 debugging，不作为安全门禁。长连接超时则保留 old，返回 pending/degraded 或 needs_reconciliation，不能强制 stop。连接排空后重新验证 route、candidate ID/health，再 stop old；stop 后 inspect 完整容器 ID 和 stopped 状态，最后才提交 previous_retired。任何路由/身份/Router/审计不确定性都保留 reservation。[HAProxy set server drain 语义](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-server/) · [show stat scur 语义](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-stat/) · [show servers conn 的调试用途](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-conn/)

## 5. Crash recovery

HAProxy Runtime API 只改运行中内存；Host map 文件是 Router 重启后的 desired state。必须同时读取文件、运行时 active map 与 durable journal；文件存在不等于 Router 已加载它。

| 崩溃点 | 可能状态 | 恢复原则 |
|---|---|---|
| pending journal 前 | old route | 尚无 switch intent；仍只读检查 |
| pending 后、map 文件前 | old route | 保留 candidate |
| map 文件后、Runtime API 前 | Router 在线时 old；重启后可能 candidate | 比较文件和运行时 map，不自动覆盖 |
| Runtime API 后、journal 更新前 | candidate route | read-back 并保留两实例 |
| route read-back 后、old drain 前 | candidate route，old 尚可接收连接 | 再确认 map，然后 drain |
| drain 后、连接排空前 | candidate route，old 有现存连接 | 有界等待，不 stop |
| old stopped 后、终态 journal 前 | candidate route，old 已 stopped | 对齐 stopped-history 崩溃窗口 |

本设计不授权自动 abort_candidate、retire_previous 或释放 needs_reconciliation。未来 reconciliation 仍需要可信 operator identity、双人 approval、证据真实性和持久化审计事务。

## 6. 迁移与兼容

现有 direct-publish deployment 已占用 host port，无法与 Router 同时绑定同一端口：
- routed deployment 必须是显式独立模式，初次部署时就创建 Router/network。
- direct-publish 部署不自动无停机接管；迁移需要维护窗口、释放旧 host port、建立 Router、启动/健康检查 app 并 read-back 验证。
- 未迁移 direct deployment 的 replacement 必须 unsupported；不允许为回滚临时 stop 旧服务。
- v1 拒绝 UDP、host networking、Windows containers、跨 daemon 和云 provider。

## 7. 安全约束

- Router admin API 仅 Unix socket，mode 600 level admin；不发布 TCP admin port。
- Router image 必须 pin digest，包含固定版本 HAProxy + socat helper，进入 SBOM/provenance 和镜像扫描。
- Docker 命令固定 argv、shell=False；Runtime API command builder 仅允许已知命令，backend/server/map 名称用 Host hash，IP/port 严格校验。
- Router state dir 0700，map/config 0600；Docker daemon capability 仅 Host 持有，不暴露给 Agent tool registry。
- Router ID、app ID、active slot、route generation 绑定同一 journal scope；read-back 不匹配即 fail closed。

## 8. 实施切片与验收

1. [x] T21.6.3.5.1 contracts（2026-11-15）：新增 runtime/deployment_traffic_router.py，定义 router scope、TCP port binding、双槽位 target、Router immutable identity、route read-back、connection drain snapshot 与 Host-only DeploymentTrafficRouter protocol；纯契约无 I/O，由 tests/test_deployment_traffic_router.py 锁定端口、IP、immutable ID、active-slot/target、generation、逐端口健康和 drain 约束。
2. T21.6.3.5.2 router bootstrap：固定 HAProxy config、user-defined network、Router image pin、Unix admin socket、固定 argv + stdin helper；fake runner 覆盖 daemon/网络/端口冲突。
   - [x] T21.6.3.5.2.1 Docker stdin boundary：Host-only SubprocessDockerRunner.execute_input() / LocalDockerProvider.execute_host_input()，subprocess.run(input=..., shell=False)，固定不可变 Router ID argv 与单条 <=1 KiB Runtime API 命令白名单。
   - [x] T21.6.3.5.2.2 pure HAProxy config builder：runtime/local_docker_router_config.py 纯函数生成 TCP frontend/backend、共享 active-slot map selector、双 weight-0 server 和 Unix admin socket；初始 map active none，不含 fallback / persistence。
   - [x] T21.6.3.5.2.3 Runtime API command builder/client：runtime/haproxy_runtime_api.py 提供 allowlisted show/get/set 命令，校验 map path、identifier、IP/port、slot/state；Host client 仅对 Router immutable ID 通过固定 socat Unix socket argv 传输。CI #602 全部通过（2,666 regression passed / 14 skipped；252 security passed / 9 skipped；Windows smoke 通过；Coverage runtime 88.40% line / 75.57% branch）。
   - T21.6.3.5.2.4 scope bridge network manager：确定性 scope 网络名与 SHA-256 标签；只创建/验证 user-defined local bridge，inspect-create-inspect 后校验 immutable network ID、driver、scope、labels、Internal=false、Attachable=false；不连接 app、不发布 host port、不创建 Router（CI 待验收）。
   - [x] T21.6.3.5.2.5 pinned Router image recipe：新增 docker/router/Dockerfile，基于 HAProxy Technologies 3.4.7 多架构 digest pin 镜像，并固定 Alpine socat package 1.8.1.3-r0；CI #607 在 Linux Docker Engine runner 实际构建镜像并验证 HAProxy/socat 版本和 OCI labels。该切片不发布镜像、不启动 Router。
   - [x] T21.6.3.5.2.6 Host image build-and-verify manager：新增 LocalDockerRouterImageManager 固定构建 context/argv，inspect 校验 image ID、平台、OCI labels、Entrypoint/Cmd；随后用 immutable image ID 执行 network=none/read-only/cap-drop-all 的临时容器，检查 HAProxy 与 socat 二进制。CI #610（run 43792885529）通过真实 Docker Engine，实际 CI 临时 image ID 为 sha256:c5d8550eeaa57d4636dd96394bac1731a0e6b1f7caf6ff05bb205d38ea98bcbe（linux/amd64）；不作为发布 artifact。仅返回 immutable image ID，不创建持久 Router container。
   - [x] T21.6.3.5.2.7 Host-owned Router state store：按 scope 建立 0700 state directory，原子写入 0600 HAProxy config 与 active-slot map，初始 active none，fsync + read-back + symlink/hardlink/owner guard；仅做 Host 文件持久化。CI #612 全部通过（2,711 regression passed / 14 skipped；252 security passed / 9 skipped；Windows E2E 和 Host Docker image manager 成功；runtime coverage 88.38% line / 75.40% branch）。
   - [x] T21.6.3.5.2.8 Router container argv + inspect identity contract：fixed `docker run` argv 仅引用 immutable image ID、已验证 scope network 与只读 Host state mounts；read-only rootfs、cap-drop ALL、最小 NET_BIND_SERVICE；Docker inspect 校验 immutable container/image/network IDs、labels、安全配置与逐端口 TCP 映射。CI #615 全部通过（2,729 regression passed / 14 skipped；252 security passed / 9 skipped；Windows/Host Docker E2E 成功；runtime coverage 88.31% line / 75.28% branch）。
   - [x] T21.6.3.5.2.9 Host Router container ensure manager：inspect-before；仅明确缺失容器允许固定 argv create；create 后不论返回码都 inspect-after；只返回 verified immutable ID；existing mismatch/daemon unavailable/timeout/port collision 均 fail closed，不 stop/rm/recreate、不切流。CI #617 全部通过（2,741 regression passed / 14 skipped；252 security passed / 9 skipped；Windows E2E、Host image manager Docker Engine、Coverage 全通过；runtime 88.34% line / 75.33% branch）。
   - [x] T21.6.3.5.2.10 HAProxy generated-config syntax validation（2026-11-17）：校验 Host state file owner/mode/link/hash 和 active none 后，以 immutable image ID、network none、read-only/cap-drop-all 临时容器将 config/map 只读挂载并运行 `haproxy -c`；CI #762 在真实 Docker Engine 上通过 HAProxy 3.4.7 验证。
   - [x] T21.6.3.5.2.11 ephemeral Docker Engine Router bootstrap + Runtime API read-back（2026-11-17，CI #762 通过）：新增 Host smoke 与 `scripts/local_docker_router_live_smoke.py`，使用临时唯一 scope 和空闲高位 host TCP port，执行 pinned image build/immutable verify、scope bridge network ensure、0700/0600 Host state persist、HAProxy -c、固定 Router container create/inspect、Runtime API show info、show map registry → map ID `#0`、`get map #0 active = none`。Router 以 Host state owner UID/GID 运行，私有 tmpfs/socket ownership 和 inspect read-back 均验证；只对 Unix socket startup 的只读 transient errors 做有界重试。最终结构化 artifact `14294272313` 报告 `status=ready`、HAProxy `3.4.7-8872a26`、map `#0`、selector `none`、cleanup `removed`；完整 CI regression 2,993/14 skipped、security 252/9 skipped、coverage 2,973/14 skipped、84% 总行覆盖率且模块 gates 全过、Windows E2E 7 passed、Docker live smoke passed。无应用容器、无 active route、无流量切换、无旧实例 retire；不构成 routed deployment 或回滚验收。
   - [x] T21.6.3.5.3.1 Host routed-app container manager（2026-11-17，CI #773 通过）：新增 `runtime/local_docker_routed_app.py` 与真实 Docker Engine smoke。Host 只使用 immutable image ID 和已验证 per-scope bridge；app 容器无 host port publish、不加入 default/host network、不允许 image-defined volumes；inspect 回读完整 immutable container ID、image ID、managed labels、唯一 bridge network ID/IP、exposed/host port metadata、capabilities/security。真实 socat fixture `healthy` 后返回 `route_eligible=true`，私有地址 `172.18.0.2`，host bindings none；cleanup 按 app immutable ID 后再删本轮 network。CI #773 Regression 3,036/14 skipped、Security 252/9 skipped、Coverage 3,016/14 skipped 且总行覆盖率 84%、Windows E2E 7 passed、Router bootstrap 与 routed-app Docker live smoke 全通过；artifact `14296334141` `status=ready`、`cleanup=removed`。不包含 HAProxy inactive slot prepare/read-back 或任何流量切换/retire。
   - [x] T21.6.3.5.4.1 Host inactive-slot preparation and read-back（2026-11-17，CI #795 通过）：`LocalDockerRouterSlotManager` 在 per-scope Host lock 内校验 Router/app immutable IDs、同 network、fresh healthy；只写非 active slot 的 server addr/port + ready state，写命令每条最多一次；read-only `show servers state` 和 scoped `show stat` 必须双重确认 exact endpoint、server state/check flags 和 `UP`，随后复查 active selector 未变化并将完整 server-state 文件原子落盘，最后重验 Router/app identity。真实 Docker Engine smoke 的 `be_p55271/slot_b` 读回 `172.18.0.3:18080`、`UP`、`check_result=3`、`check_state=6`、`scur=0`；selector 始终 `none`，无 active map mutation；app/Router/network cleanup 全部 removed。CI #795 全绿：Regression 3,084/14 skipped、Security 252/9 skipped、Coverage 3,064/14 skipped、总行覆盖率 84%、Windows E2E 7 passed；artifact `14298667951` status ready。**不包含 active-slot switch、业务流量、drain/retire 或重启恢复验收。**3. T21.6.3.5.3 routed deployment：应用容器不 publish，Router 唯一 publish；TCP-only validation；Router identity 与 host ports 持久化。
4. T21.6.3.5.4 candidate + route map：双 slot、单 active-slot map、map 文件原子持久化、Runtime API command builder、read-back。
5. T21.6.3.5.5 coordinator integration：traffic_switch_pending、持久化 intent、atomic map switch、old drain/连接排空/inspect-confirmed retire。
6. T21.6.3.5.6 daemon-backed E2E：真实 Docker Engine 验证首次部署、两实例同端口共存、切换后 route marker、Router restart、API timeout/error/身份错配/连接不排空注入；无 daemon 必须标记 unavailable，fake runner 不可冒充真实 E2E。
7. Approval/audit gate：可信 Host identity、双人独立审批、evidence digest 和 durable audit-before-journal transition 未完成前，不实现 reconciliation mutation。

   - [x] T21.6.3.5.4.2 Host active-slot map switch and TCP route read-back（2026-11-17，CI #800 待验证）：LocalDockerRouterSlotManager.switch_active_slot() 在与 inactive-slot preparation 共用的 per-scope Host lock 内校验 Router/app immutable identity、scope/network/port bindings、fresh HEALTHCHECK 与目标 slot 每个 backend 的 exact address/port、HAProxy check flags 和 UP。随后 LocalDockerRouterStateStore.persist_active_slot_map() 以 expected-prior selector、现有 SHA-256、owner/mode/link/symlink 检查为前提原子写入 Host restart map 并 fsync/read-back；仅发送一次 set map #0 active <slot>，无论写命令返回成功或失败均以 get map 读回为准，切换后再次验证 backend、selector 和 Router/app immutable IDs。读回仍为旧 selector 时仅恢复 Host desired-state 文件；结果不明时保留目标 map 文件并返回 indeterminate，不重试、不自动回滚、不 retire。新增单测覆盖成功、ambiguous write-but-applied、write rejected + prior selector read-back、read-back timeout、selector precondition mismatch、backend DOWN 与 cross-scope refusal。Docker Engine live smoke 扩展为 slot_b active switch，并通过 Router published TCP port 获取 app 唯一 marker ROUTED_APP_OK。CI #801（run 44024362240，commit 69ad157c）全部通过：Regression 3,100/14 skipped、Security 252/9 skipped、Coverage baseline 3,080/14 skipped、总行覆盖率 84% 且全部模块行/分支 floors 通过、Windows E2E 7 passed、真实 Docker Engine active-slot/TCP marker smoke passed；artifact 14302043129 status ready，cleanup removed。本切片不证明旧实例双槽蓝绿替换、drain/retire、Router restart crash recovery 或自动 rollback。

### T21.6.3.5.5 Durable replacement coordinator integration（2026-11-17，CI #840 全部通过）

- 新增 LocalDockerRouterReplacementProvider，实现现有 DeploymentReplacementProvider 能力契约，接入 HostDeploymentReplacementManager；不另建第二套事务状态机。候选部署必须与 Router scope 的 provider/project/environment 完全一致，previous deployment 的 immutable runtime ID、active Router target、slot inventory 与实时 Runtime API selector/read-back 必须一致，才可预留 inactive slot。
- Candidate start 只使用 immutable image ID，在已验证 scope bridge 内创建 routed app，不发布 app host port；Host app inspect 必须确认 immutable container/image/network/IP/port binding 与 fresh HEALTHCHECK。随后执行 inactive-slot prepare/read-back，并通过 SQLite route-generation + active-map digest CAS 持久化候选 slot target。
- 复用 coordinator 已有的 traffic_switch_pending durable intent：journal intent 提交后，slot manager 原子写入 Host active map，HAProxy Runtime API 的 set map 只尝试一次，随后必须 get map read-back；只有 selector、目标 backend 和 Router/app identity 全部验证成功，provider 才 CAS 更新 Router registry active slot/target。Coordinator 再独立 read-back effective runtime target，之后才推进 deployment active-pointer CAS。
- Previous retirement 仅在 candidate route read-back 与 active-pointer CAS 完成后开始：每个旧 slot backend 一次性切入 DRAIN；只轮询只读 show stat，必须全部处于 DRAIN 且 scur=0 才进入 MAINT；MAINT + zero-session read-back 成功后原子持久化 server-state，再通过完整 immutable container ID 执行 stop，并 inspect 确认同一 ID 已退出。最后 CAS 移除 retired slot target。容器不自动 rm，保留 Host 可审计资源。
- 任一 Runtime API/SQLite/Docker 结果不明、drain 超时或 identity/read-back 不匹配均不重试、不自动反向切流、不删除实例；coordinator 进入 needs_reconciliation 并保留 scope reservation。Coordinator 现在把 provider retirement/abort 的失败详情写入 reconciliation journal，避免丢失 drain 超时等关键证据。Drain timeout integration test 证明旧实例仍运行且不会被停止；active pointer 已按切流阶段推进时，恢复必须走人工 reconciliation。
- 新增完整 fake-provider integration test，贯通 HostDeploymentReplacementManager 的 journal phases、candidate start/health、Router slot prepare、active map switch、live selector read-back、active pointer CAS、旧连接 drain 和 immutable-ID retire；另覆盖 drain timeout 保留旧实例的失败路径。Runtime selector fixture 与 SQLite registry 独立，避免用 registry 值代替 Runtime API read-back。
- CI #840（run 44038726599，commit 95492c7664）全部通过：Regression 3,130 passed / 14 skipped；Security 252 passed / 9 skipped；Coverage baseline 总行覆盖率 83%，agents 86.76/74.44、core 89.85/74.44、runtime 87.02/73.85、security 74.02/66.22、tools 67.92/63.56（line/branch，全部高于门槛）；Windows Python/Node.js E2E 7 passed；Docker Engine Router lifecycle / active-slot / TCP marker smoke passed。
- 证据边界：完整 replacement coordinator 集成目前由 fake-provider integration 测试覆盖；Docker Engine job 仍验证 Router lifecycle、active-slot switch 与 TCP marker，不代表已在 daemon 上实测两个真实 app 的完整蓝绿替换、DRAIN/MAINT 连接排空、crash recovery 或 rollback。上述内容转入 T21.6.3.5.6 daemon-backed E2E；reconciliation mutation 的审批/审计门仍未实现，recovery inventory 保持只读。

## 9. 未实现边界

仓库已具备 Router contracts、HAProxy config renderer、Host allowlisted Runtime API client、scope network manager、pinned Router image、Host state store、Router container manager、routed-app manager、inactive-slot preparation、active-slot switch manager、Host Router lifecycle manager 与 durable replacement provider adapter。CI #762/#783 验证 Router bootstrap 和初始空路由；CI #773 验证 app candidate identity/health；CI #795 验证 inactive slot backend UP/read-back 与 server-state 持久化。T21.6.3.5.4.2 新增 Host desired-map 原子写入、单次 Runtime API map mutation、selector/backend/identity read-back，并把真实 Docker Engine smoke 扩展为 Router TCP route marker；CI #801 全部通过。T21.6.3.5.5 新增 coordinator replacement 与 drain/retire 的 fake-provider integration，CI #840 全部通过（Regression 3,130/14 skipped、Security 252/9 skipped、Coverage 总行覆盖率 83% 且所有模块 line/branch floors 全过、Windows E2E 7 passed、Docker Engine Router lifecycle/active-slot/TCP marker smoke passed）。当前仍未完成 daemon-backed 双 app 同端口共存与真实切换 marker、Router restart 后 server-state/map/journal crash consistency、真实 Docker Engine DRAIN/MAINT 连接排空与 retire、以及 timeout/身份错配等 daemon failure-injection E2E；这些属于 T21.6.3.5.6。needs_reconciliation 继续锁定，Local Docker zero-downtime rollback 仍 unsupported。
## 10. 参考资料

- HAProxy Technologies verified publisher image, version 3.4.7: https://hub.docker.com/r/haproxytech/haproxy-alpine
- HAProxy 3.4.7 multi-platform image index digest: https://hub.docker.com/layers/haproxytech/haproxy-alpine/3.4.7/images/sha256-8ee937ab858c6443525e727f1f54109633cd247b808ddc2e76b14aea673066a0
- Alpine Linux v3.23 socat package version/license metadata: https://pkgs.alpinelinux.org/packages?branch=v3.23&name=socat
- Docker image digest and multi-platform index semantics: https://docs.docker.com/dhi/explore/security-concepts/digests/

- Docker user-defined bridge: https://docs.docker.com/engine/network/ and https://docs.docker.com/engine/network/drivers/bridge/
- HAProxy Runtime API / in-memory state: https://www.haproxy.com/documentation/haproxy-runtime-api/
- set server: https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-server/
- use-server in TCP/HTTP mode: https://docs.haproxy.org/3.4/configuration.html
- show servers state / show stat (scur): https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-state/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-stat/
- show servers conn (diagnostic only): https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-conn/
- set map / prepare map / commit map: https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-map/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/prepare-map/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/commit-map/
- Unix socket security: https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/management/

Runtime API map read-back resolves the numeric map ID from the read-only `show map` registry and verifies the exact in-container map path before issuing `get map #ID active`. Host state file paths must never be sent to the in-container Runtime API. The live bootstrap smoke expects the returned selector to be exactly `none`.
