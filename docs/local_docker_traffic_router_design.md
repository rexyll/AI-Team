# Local Docker 蓝绿流量路由设计（T21.6.3.5）

> **状态：设计决策已形成，实现尚未开始；不能据此声称 Local Docker 支持安全替换或零停机回滚。**  
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

Router 只开放 Unix stats socket（mode 600, level admin），不发布 admin TCP port。Host 通过固定 argv 的 docker exec -i + socat 连接，不经过 shell。[HAProxy Unix socket management](https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/management/)

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

### 4.1 一个 selector 驱动所有端口

每个端口 backend 定义两个 server slots，并通过 HAProxy map fetch + use-server 规则选择 slot。所有 frontend 查询相同 active-slot map key，因此多端口不需要逐个切换。一次 set map <map-id> active_slot slot_b 是唯一 route switch；不得循环改端口并声称整个 scope 原子切换。

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
5. Runtime API read-back：get/show map 验证 active slot；show servers state/show stat 验证每个 backend 的候选地址、端口和 UP 状态；与 Router ID、candidate Docker immutable ID 和 network IP 交叉核验。
6. 全部读回匹配后，journal 才能进入 traffic_switched，active pointer 才能 CAS 更新。

API 超时/错误不能凭命令返回值猜测切换结果；必须 read-back。确认指向 old/candidate 才能报告 observed route；unknown、地址不匹配、Router ID 不符、backend 缺项一律 needs_reconciliation，并保留两实例与 scope reservation。

### 4.4 Drain previous

route 指向 candidate 且 read-back 成功后，将 old slot 设为 drain，停止新连接分配但允许现有会话完成。Host 对 old server active connections 有界轮询并要求连续稳定为零；长连接超时则保留 old，返回 pending/degraded 或 needs_reconciliation，不能强制 stop。连接排空后重新验证 route、candidate ID/health，再 stop old；stop 后 inspect 完整容器 ID 和 stopped 状态，最后才提交 previous_retired。任何路由/身份/Router/审计不确定性都保留 reservation。

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
3. T21.6.3.5.3 routed deployment：应用容器不 publish，Router 唯一 publish；TCP-only validation；Router identity 与 host ports 持久化。
4. T21.6.3.5.4 candidate + route map：双 slot、单 active-slot map、map 文件原子持久化、Runtime API command builder、read-back。
5. T21.6.3.5.5 coordinator integration：traffic_switch_pending、持久化 intent、atomic map switch、old drain/连接排空/inspect-confirmed retire。
6. T21.6.3.5.6 daemon-backed E2E：真实 Docker Engine 验证首次部署、两实例同端口共存、切换后 route marker、Router restart、API timeout/error/身份错配/连接不排空注入；无 daemon 必须标记 unavailable，fake runner 不可冒充真实 E2E。
7. Approval/audit gate：可信 Host identity、双人独立审批、evidence digest 和 durable audit-before-journal transition 未完成前，不实现 reconciliation mutation。

## 9. 未实现边界

本文件只是设计决策。仓库尚无 HAProxy router image、scope network manager、routed deployment path、Runtime API client、route read-back、traffic_switch_pending phase 或 daemon-backed E2E。Local Docker rollback/zero-downtime 仍 unsupported；needs_reconciliation 继续锁定。

## 10. 参考资料

- Docker user-defined bridge: https://docs.docker.com/engine/network/ and https://docs.docker.com/engine/network/drivers/bridge/
- HAProxy Runtime API / in-memory state: https://www.haproxy.com/documentation/haproxy-runtime-api/
- set server: https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-server/
- show servers state / stat / conn: https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-state/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-stat/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/show-servers-conn/
- set map / prepare map / commit map: https://www.haproxy.com/documentation/haproxy-runtime-api/reference/set-map/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/prepare-map/ and https://www.haproxy.com/documentation/haproxy-runtime-api/reference/commit-map/
- Unix socket security: https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/management/
