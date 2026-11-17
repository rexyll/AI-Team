# Local Docker 蓝绿流量路由设计（T21.6.3.5）

> **状态：架构设计已完成；Host-only contracts、配置生成器、Runtime API 的 Unix socket 通过有界只读就绪轮询确认；启动竞态不扩大写操作重试边界。
Runtime API 命令通道已通过 CI。scope network manager 已实现并通过 CI #604；Router image recipe 正在进行 pinned-build CI 验收；Router container、真实 Runtime API read-back、流量切换和 daemon-backed E2E 仍未完成。不得据此声称 Local Docker 已支持安全替换或零停机回滚。**  
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
   - T21.6.3.5.2.10 HAProxy generated-config syntax validation（当前）：校验 Host state file owner/mode/link/hash 和 active none 后，以 immutable image ID、network none、read-only/cap-drop-all 临时容器将 config/map 只读挂载并运行 haproxy -c；加入 Host Docker CI job 真实验证生成配置可被 HAProxy 3.4.7 加载；不创建持久 Router 或发布 host port。
   - T21.6.3.5.2.11 ephemeral Docker Engine Router bootstrap + Runtime API read-back（2026-11-17，CI 待验收）：新增独立 Host smoke 脚本，使用临时唯一 scope 和空闲高位 host TCP port，顺序执行 pinned image build/immutable verify、scope bridge network ensure、0700/0600 Host state persist、HAProxy -c、固定 Router container create/inspect、Runtime API show info 与 active map get。仅验证 Router 实例真实启动、HAProxy 3.4.7 在线、初始 selector 为 none；没有应用容器、没有 active route、没有流量切换、没有旧实例 retire。测试在 finally 中仅按本次 verified immutable Router/network ID 清理自己创建的临时资源，并上传结构化证据；不构成 routed deployment 或回滚验收。
3. T21.6.3.5.3 routed deployment：应用容器不 publish，Router 唯一 publish；TCP-only validation；Router identity 与 host ports 持久化。
4. T21.6.3.5.4 candidate + route map：双 slot、单 active-slot map、map 文件原子持久化、Runtime API command builder、read-back。
5. T21.6.3.5.5 coordinator integration：traffic_switch_pending、持久化 intent、atomic map switch、old drain/连接排空/inspect-confirmed retire。
6. T21.6.3.5.6 daemon-backed E2E：真实 Docker Engine 验证首次部署、两实例同端口共存、切换后 route marker、Router restart、API timeout/error/身份错配/连接不排空注入；无 daemon 必须标记 unavailable，fake runner 不可冒充真实 E2E。
7. Approval/audit gate：可信 Host identity、双人独立审批、evidence digest 和 durable audit-before-journal transition 未完成前，不实现 reconciliation mutation。

## 9. 未实现边界

仓库已具备 Router contracts、HAProxy config renderer、allowlisted Runtime API client、scope network manager、pinned Router image recipe、Host image build-and-verify manager（CI #610）、Host-owned state store（CI #612）、Router container argv/inspect contract（CI #615）和 Host Router container ensure manager（CI #617）。HAProxy generated-config syntax validator 正在 CI 验收中。尚无经 CI 验收的持久 Router 容器启动、Runtime API route read-back、traffic_switch_pending、routed app deployment 或真实蓝绿流量切换；needs_reconciliation 继续锁定，Local Docker zero-downtime rollback 仍 unsupported。
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
