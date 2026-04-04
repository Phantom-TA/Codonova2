import React, { useState, useEffect } from 'react'

function StatCard({ title, value, sub, color = '#8b5cf6', icon }) {
  return (
    <div className="glass-card p-4 flex items-start gap-3">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 text-lg"
        style={{ background: color + '20', color }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-slate-500 mb-0.5">{title}</div>
        <div className="font-bold text-lg text-white truncate">{value}</div>
        {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
      </div>
    </div>
  )
}

function RankTable({ title, rows, columns, emptyMsg }) {
  return (
    <div className="glass-card p-4">
      <h4 className="text-sm font-semibold text-slate-300 mb-3">{title}</h4>
      {!rows || rows.length === 0 ? (
        <p className="text-xs text-slate-600">{emptyMsg || 'No data yet'}</p>
      ) : (
        <div className="space-y-2">
          {rows.slice(0, 8).map((row, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="text-xs text-slate-600 w-5 text-right flex-shrink-0">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  {columns.map(col => (
                    <span
                      key={col.key}
                      className={`text-xs ${col.primary ? 'text-slate-300 font-medium truncate' : 'text-slate-500 flex-shrink-0'}`}
                    >
                      {col.format ? col.format(row[col.key]) : row[col.key]}
                    </span>
                  ))}
                </div>
                {/* Progress bar for numeric values */}
                {columns[1] && typeof row[columns[1].key] === 'number' && (
                  <div className="mt-1 h-1 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-brand-500"
                      style={{
                        width: `${Math.min(100, (row[columns[1].key] / (rows[0][columns[1].key] || 1)) * 100)}%`,
                        opacity: 0.7,
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function InsightsPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchInsights = async () => {
    try {
      const res = await fetch('/api/insights')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchInsights()
    const interval = setInterval(fetchInsights, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="pulse-dot bg-brand-400 w-4 h-4"></div>
          <p className="text-slate-500 text-sm">Loading insights...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400 text-sm flex-col gap-2">
        <span>⚠ Failed to load insights</span>
        <span className="text-xs text-slate-600">{error}</span>
        <button onClick={fetchInsights} className="text-xs text-brand-400 hover:underline mt-2">
          Retry
        </button>
      </div>
    )
  }

  const agents = data?.agent_retry_rates || []
  const bugs = data?.recurring_bugs || []
  const failedTypes = data?.most_failed_task_types || []
  const patterns = data?.reused_patterns || []

  const totalTasks = agents.reduce((s, a) => s + (a.tasks || 0), 0)
  const totalRetries = agents.reduce((s, a) => s + (a.retries || 0), 0)
  const avgScore = agents.length
    ? (agents.reduce((s, a) => s + (a.avg_score || 0), 0) / agents.length).toFixed(1)
    : 'N/A'

  return (
    <div className="space-y-4 h-full overflow-y-auto pr-1">
      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard title="Tasks Completed" value={totalTasks} icon="✓" color="#10b981" />
        <StatCard title="Total Retries" value={totalRetries} icon="↺" color="#f59e0b" />
        <StatCard title="Avg Agent Score" value={`${avgScore}/10`} icon="★" color="#8b5cf6" />
        <StatCard title="Recurring Bugs" value={bugs.length} icon="🐛" color="#ef4444" />
      </div>

      {/* Agent performance */}
      <RankTable
        title="🤖 Agent Performance"
        rows={agents}
        columns={[
          { key: 'agent', primary: true },
          { key: 'avg_score', format: v => `${(v || 0).toFixed(1)}/10` },
          { key: 'retry_rate', format: v => `${((v || 0) * 100).toFixed(0)}% retry` },
        ]}
        emptyMsg="No agent data yet"
      />

      {/* Recurring bugs */}
      <RankTable
        title="🐛 Recurring Bug Types"
        rows={bugs}
        columns={[
          { key: 'error_type', primary: true },
          { key: 'frequency', format: v => `${v}x` },
        ]}
        emptyMsg="No bugs recorded — great!"
      />

      {/* Failed task types */}
      <RankTable
        title="⚠ Most Failed Task Types"
        rows={failedTypes}
        columns={[
          { key: 'task_type', primary: true },
          { key: 'failure_count', format: v => `${v} failures` },
        ]}
        emptyMsg="No failed tasks"
      />

      {/* Memory patterns */}
      <RankTable
        title="🧠 Reused Code Patterns"
        rows={patterns}
        columns={[
          { key: 'pattern', primary: true },
          { key: 'uses', format: v => `${v || 0} uses` },
        ]}
        emptyMsg="No patterns in memory yet"
      />

      <p className="text-xs text-slate-600 text-center pb-2">
        Last updated: {data?.generated_at ? new Date(data.generated_at).toLocaleTimeString() : '—'}
      </p>
    </div>
  )
}
