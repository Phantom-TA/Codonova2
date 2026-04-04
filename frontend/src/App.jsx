import React, { useState, useEffect, useCallback } from 'react'
import TaskGraph from './components/TaskGraph.jsx'
import AgentFeed from './components/AgentFeed.jsx'
import CodeViewer from './components/CodeViewer.jsx'
import EvalChart from './components/EvalChart.jsx'
import InsightsPanel from './components/InsightsPanel.jsx'

// ─── Panel Definitions ────────────────────────────────────────────────────────
const PANELS = [
  { id: 'graph',    label: 'Task Graph',   icon: '⬡', component: TaskGraph },
  { id: 'feed',     label: 'Agent Feed',   icon: '⚡', component: AgentFeed },
  { id: 'code',     label: 'Code Viewer',  icon: '⌨', component: CodeViewer },
  { id: 'eval',     label: 'Evaluations',  icon: '★',  component: EvalChart },
  { id: 'insights', label: 'Insights',     icon: '◈',  component: InsightsPanel },
]

// ─── Status Colors ─────────────────────────────────────────────────────────
const STATUS_COLOR = {
  PLANNED:              '#8b5cf6',
  RUNNING:              '#3b82f6',
  COMPLETED:            '#10b981',
  COMPLETED_WITH_ERRORS:'#f59e0b',
  FAILED:               '#ef4444',
}

// ─── Project Status Bar ────────────────────────────────────────────────────
function ProjectStatusBar({ status, projectId }) {
  if (!status) return null
  const pct = status.progress_pct || 0
  const color = STATUS_COLOR[status.status] || '#64748b'

  return (
    <div className="glass-card px-4 py-2.5 flex items-center gap-4 animate-fade-in">
      <div className="min-w-0">
        <span className="text-xs text-slate-400">Project: </span>
        <span className="text-xs text-slate-200 font-medium">{status.title}</span>
        <span className="text-xs text-slate-600 ml-2 font-mono">{projectId?.slice(0, 8)}</span>
      </div>
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden min-w-0">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${pct}%`, background: color }}
          />
        </div>
        <span className="text-xs font-semibold flex-shrink-0" style={{ color }}>{pct}%</span>
      </div>
      <div className="flex gap-3 text-xs text-slate-500 flex-shrink-0">
        <span className="text-green-400">{status.tasks?.done || 0} done</span>
        <span className="text-red-400">{status.tasks?.failed || 0} failed</span>
        <span className="text-blue-400">{status.tasks?.in_progress || 0} active</span>
      </div>
    </div>
  )
}

// ─── Pipeline Launcher ─────────────────────────────────────────────────────
function PipelineLauncher({ onLaunched, loading, setLoading }) {
  const [requirement, setRequirement] = useState('')
  const [mode, setMode] = useState('plan') // 'plan' | 'start'
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!requirement.trim()) return
    setLoading(true)
    setError('')
    try {
      const endpoint = mode === 'plan' ? '/api/plan' : '/api/start'
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requirement }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Request failed')
      }
      const data = await res.json()
      setResult(data)
      onLaunched(data.project_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="glass-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-200 flex items-center gap-2">
          <span className="text-brand-400">⚡</span>
          Launch Pipeline
        </h2>
        <div className="flex items-center gap-1 p-1 bg-white/5 rounded-lg">
          {['plan', 'start'].map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-all ${
                mode === m ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'
              }`}
            >
              {m === 'plan' ? '📋 Plan Only' : '🚀 Full Pipeline'}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <textarea
          value={requirement}
          onChange={e => setRequirement(e.target.value)}
          className="w-full h-28 px-4 py-3 bg-white/[0.04] border border-white/10 rounded-xl
                     text-sm text-slate-200 placeholder-slate-600 resize-none
                     focus:outline-none focus:border-brand-500/50 focus:bg-white/[0.06]
                     transition-all font-mono leading-relaxed"
          placeholder={
            mode === 'start'
              ? 'Describe what to build, e.g.:\n"Build a REST API for a student grade management system with endpoints to add students, record grades, and calculate GPA. Use FastAPI and SQLite."'
              : 'Describe your requirements...'
          }
        />
        {error && (
          <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading || !requirement.trim()}
          className="w-full py-2.5 rounded-xl font-semibold text-sm transition-all
                     bg-gradient-to-r from-brand-600 to-brand-500 text-white
                     hover:from-brand-500 hover:to-brand-400
                     disabled:opacity-40 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 glow-brand"
        >
          {loading ? (
            <><span className="pulse-dot bg-white"></span> Processing...</>
          ) : (
            mode === 'plan' ? '📋 Analyze & Plan' : '🚀 Start Autonomous Pipeline'
          )}
        </button>
      </form>

      {result && (
        <div className="text-xs bg-white/[0.03] border border-white/5 rounded-lg p-3 space-y-1.5 animate-slide-up">
          <div className="flex gap-2">
            <span className="text-slate-500">Project ID:</span>
            <span className="font-mono text-brand-400">{result.project_id?.slice(0, 8)}…</span>
          </div>
          <div className="flex gap-2">
            <span className="text-slate-500">Features:</span>
            <span className="text-slate-300">{result.feature_count}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-slate-500">Tasks:</span>
            <span className="text-slate-300">{result.task_count}</span>
          </div>
          {result.status && (
            <div className="flex gap-2">
              <span className="text-slate-500">Status:</span>
              <span className="text-green-400">{result.status}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Project Selector ──────────────────────────────────────────────────────
function ProjectSelector({ activeProjectId, onSelect }) {
  const [projects, setProjects] = useState([])

  useEffect(() => {
    fetch('/api/projects')
      .then(r => r.json())
      .then(data => setProjects(data || []))
      .catch(console.error)

    const interval = setInterval(() => {
      fetch('/api/projects')
        .then(r => r.json())
        .then(data => setProjects(data || []))
        .catch(() => {})
    }, 15000)
    return () => clearInterval(interval)
  }, [])

  if (projects.length === 0) return null

  return (
    <div className="space-y-1.5">
      <div className="text-xs text-slate-500 px-1">Recent Projects</div>
      {projects.slice(0, 6).map(p => (
        <button
          key={p.id}
          onClick={() => onSelect(p.id)}
          className={`w-full text-left px-3 py-2.5 rounded-lg text-xs transition-all flex items-center gap-2 ${
            activeProjectId === p.id
              ? 'bg-brand-600/20 border border-brand-600/40 text-brand-300'
              : 'hover:bg-white/5 text-slate-400 hover:text-slate-200 border border-transparent'
          }`}
        >
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: STATUS_COLOR[p.status] || '#64748b' }}
          />
          <span className="truncate flex-1">{p.title || 'Untitled'}</span>
          <span className="text-slate-600 flex-shrink-0">{p.task_count}t</span>
        </button>
      ))}
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────
export default function App() {
  const [activePanel, setActivePanel] = useState('graph')
  const [projectId, setProjectId] = useState(null)
  const [projectStatus, setProjectStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // Fetch project status periodically
  useEffect(() => {
    if (!projectId) return
    const fetch_status = async () => {
      try {
        const res = await fetch(`/api/status/${projectId}`)
        if (res.ok) {
          const data = await res.json()
          setProjectStatus(data)
        }
      } catch (e) { /* ignore */ }
    }
    fetch_status()
    const interval = setInterval(fetch_status, 8000)
    return () => clearInterval(interval)
  }, [projectId])

  const handleExport = async () => {
    if (!projectId) return
    try {
      const res = await fetch(`/api/export/${projectId}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `codonova_export_${projectId.slice(0, 8)}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('Export failed: ' + e.message)
    }
  }

  const ActivePanel = PANELS.find(p => p.id === activePanel)?.component
  const panelProps = {
    projectId,
    onNodeClick: (node) => {
      // Clicking a code module node switches to code viewer
      if (node.type === 'CodeModule') setActivePanel('code')
    },
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-primary)]">
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside
        className={`
          flex-shrink-0 flex flex-col border-r border-white/5
          transition-all duration-300 bg-[var(--bg-secondary)]
          ${sidebarOpen ? 'w-72' : 'w-16'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-white/5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center text-sm font-bold flex-shrink-0">
            C
          </div>
          {sidebarOpen && (
            <div className="min-w-0">
              <div className="font-bold gradient-text text-sm">Codonova</div>
              <div className="text-[10px] text-slate-600">Autonomous Dev System</div>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="ml-auto text-slate-600 hover:text-slate-400 transition-colors flex-shrink-0"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d={sidebarOpen ? "M11 19l-7-7 7-7m8 14l-7-7 7-7" : "M13 5l7 7-7 7M5 5l7 7-7 7"} />
            </svg>
          </button>
        </div>

        {/* Panel nav */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {PANELS.map(panel => (
            <button
              key={panel.id}
              id={`nav-${panel.id}`}
              onClick={() => setActivePanel(panel.id)}
              className={`
                w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                transition-all group relative
                ${activePanel === panel.id
                  ? 'bg-brand-600/20 text-brand-300 border border-brand-600/30'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
                }
              `}
            >
              <span className="text-base flex-shrink-0">{panel.icon}</span>
              {sidebarOpen && <span className="font-medium">{panel.label}</span>}
              {!sidebarOpen && (
                <span className="absolute left-full ml-2 px-2 py-1 bg-slate-800 text-xs text-slate-200 rounded
                                 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 border border-white/10">
                  {panel.label}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Project selector (sidebar open) */}
        {sidebarOpen && (
          <div className="p-3 border-t border-white/5 space-y-3">
            <ProjectSelector activeProjectId={projectId} onSelect={setProjectId} />

            {/* Export button */}
            {projectId && (
              <button
                onClick={handleExport}
                id="btn-export"
                className="w-full py-2 rounded-lg text-xs text-slate-400 hover:text-white
                           bg-white/5 hover:bg-white/10 transition-all flex items-center justify-center gap-2"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Export ZIP
              </button>
            )}

            {/* Neo4j link */}
            <a
              href="http://localhost:7474"
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full py-2 rounded-lg text-xs text-slate-500 hover:text-slate-300
                         bg-white/[0.03] hover:bg-white/5 transition-all text-center"
            >
              Open Neo4j Browser ↗
            </a>
          </div>
        )}
      </aside>

      {/* ── Main Area ────────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-shrink-0">
          <div>
            <h1 className="text-base font-semibold text-slate-200 flex items-center gap-2">
              {PANELS.find(p => p.id === activePanel)?.icon}
              {PANELS.find(p => p.id === activePanel)?.label}
            </h1>
            {projectId && (
              <p className="text-xs text-slate-500 mt-0.5 font-mono">
                project: {projectId.slice(0, 16)}…
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              API Docs ↗
            </a>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden flex gap-5 p-5">
          {/* Main panel */}
          <div className="flex-1 flex flex-col gap-4 overflow-hidden">
            {/* Project status bar */}
            {projectStatus && (
              <ProjectStatusBar status={projectStatus} projectId={projectId} />
            )}

            {/* Active panel */}
            <div className="flex-1 glass-card p-4 overflow-hidden animate-fade-in">
              {ActivePanel && <ActivePanel {...panelProps} />}
            </div>
          </div>

          {/* Right sidebar: launcher */}
          <div className="w-80 flex-shrink-0 flex flex-col gap-4">
            <PipelineLauncher
              onLaunched={setProjectId}
              loading={loading}
              setLoading={setLoading}
            />

            {/* Quick stats for mobile - condensed */}
            {projectStatus && (
              <div className="glass-card p-4 space-y-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pipeline State</h3>
                {[
                  { label: 'Status', value: projectStatus.status, color: STATUS_COLOR[projectStatus.status] || '#94a3b8' },
                  { label: 'Done', value: `${projectStatus.tasks?.done || 0} tasks`, color: '#10b981' },
                  { label: 'In Progress', value: `${projectStatus.tasks?.in_progress || 0} tasks`, color: '#3b82f6' },
                  { label: 'Failed', value: `${projectStatus.tasks?.failed || 0} tasks`, color: '#ef4444' },
                  { label: 'Blocked', value: `${projectStatus.tasks?.blocked || 0} tasks`, color: '#f59e0b' },
                ].map(item => (
                  <div key={item.label} className="flex justify-between text-xs">
                    <span className="text-slate-500">{item.label}</span>
                    <span className="font-medium" style={{ color: item.color }}>{item.value}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Mini agent feed always visible */}
            <div className="flex-1 glass-card p-4 overflow-hidden flex flex-col min-h-0">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Live Feed
              </h3>
              <div className="flex-1 overflow-hidden">
                <AgentFeed projectId={projectId} />
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
