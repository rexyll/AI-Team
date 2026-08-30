from __future__ import annotations

from html import escape

from runtime.observability_dashboard import DashboardSnapshot



def render_dashboard(snapshot: DashboardSnapshot) -> str:
    """Render a dependency-free, read-only operational dashboard."""
    workflow = snapshot.workflow
    agent_rows = "".join(
        "<tr>"
        f"<td>{escape(agent.role)}</td>"
        f"<td>{agent.task_count}</td>"
        f"<td>{agent.completed}</td>"
        f"<td>{agent.failed}</td>"
        f"<td>{agent.active}</td>"
        f"<td>{agent.success_rate:.1%}</td>"
        f"</tr>"
        for agent in snapshot.agents
    ) or '<tr><td colspan="6">No agent data</td></tr>'
    task_rows = "".join(
        "<tr>"
        f"<td>{escape(task.task_id)}</td>"
        f"<td>{escape(task.title)}</td>"
        f"<td>{escape(task.role)}</td>"
        f"<td>{escape(task.status)}</td>"
        f"<td>{escape(task.trace_id or '—')}</td>"
        f"</tr>"
        for task in snapshot.tasks
    ) or '<tr><td colspan="5">No task data</td></tr>'

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Team Operational Dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#f6f7f9;color:#172033}}
main{{max-width:1200px;margin:auto}}h1{{margin-bottom:4px}}.meta{{color:#667085;margin-bottom:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:white;border:1px solid #dfe3e8;border-radius:10px;padding:16px}}.value{{font-size:28px;font-weight:700;margin-top:6px}}
section{{background:white;border:1px solid #dfe3e8;border-radius:10px;padding:16px;margin-bottom:16px;overflow:auto}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #edf0f2;white-space:nowrap}}
th{{font-size:12px;text-transform:uppercase;color:#667085}}
</style></head>
<body><main>
<h1>AI-Team Operational Dashboard</h1>
<div class="meta">Project: {escape(snapshot.project_id or '—')} · Generated: {escape(snapshot.generated_at)}</div>
<div class="grid">
<div class="card">Total tasks<div class="value">{workflow.total_tasks}</div></div>
<div class="card">Completed<div class="value">{workflow.completed}</div></div>
<div class="card">Failed<div class="value">{workflow.failed}</div></div>
<div class="card">Blocked<div class="value">{workflow.blocked}</div></div>
<div class="card">Active<div class="value">{workflow.active}</div></div>
<div class="card">Success rate<div class="value">{workflow.success_rate:.1%}</div></div>
</div>
<section><h2>Agents</h2><table><thead><tr><th>Role</th><th>Tasks</th><th>Completed</th><th>Failed</th><th>Active</th><th>Success</th></tr></thead><tbody>{agent_rows}</tbody></table></section>
<section><h2>Tasks</h2><table><thead><tr><th>ID</th><th>Title</th><th>Role</th><th>Status</th><th>Trace</th></tr></thead><tbody>{task_rows}</tbody></table></section>
</main></body></html>'''
