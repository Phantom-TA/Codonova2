import React, { useEffect, useState, useCallback } from 'react'

// ─── Constants ────────────────────────────────────────────────────────────────

const NAMED_AGENTS = [
  { key: 'PlanningAgent',   color: '#a78bfa', role: 'Decomposes requirements into tasks' },
  { key: 'DeveloperAgent',  color: '#3b82f6', role: 'Generates code for each task'       },
  { key: 'TestingAgent',    color: '#10b981', role: 'Writes & runs Jest tests'            },
  { key: 'EvaluatorAgent',  color: '#f59e0b', role: 'Scores code quality 0–10'           },
  { key: 'DebuggingAgent',  color: '#ef4444', role: 'Fixes failed tasks automatically'   },
]

const TIER_META = {
  reasoning: { label: 'Reasoning Model', color: '#8b5cf6' },
  fast:      { label: 'Fast Model',      color: '#3b82f6' },
  unknown:   { label: 'Unknown',         color: '#64748b' },
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }) {
  return (
    <div className="glass-card p-4 flex flex-col gap-1">
      <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
      <span className="text-2xl font-bold" style={{ color: color || '#e2e8f0' }}>{value}</span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  )
}

function ModelTierCard({ tier, stats, totalTokens }) {
  const meta      = TIER_META[tier] || TIER_META.unknown
  const tokens    = stats?.total_tokens    || 0
  const calls     = stats?.total_calls     || 0
  const success   = stats?.success_rate_pct ?? 0
  const latency   = stats?.avg_latency_ms  || 0
  const failed    = stats?.failed_calls    || 0
  const pct       = totalTokens > 0 ? Math.round((tokens / totalTokens) * 100) : 0
  const models    = stats?.models_used || []
  // Show actual model name detected at runtime
  const modelName = models.length > 0 ? models[0] : 'Not yet used'

  const successColor = success >= 90 ? '#10b981' : success >= 70 ? '#f59e0b' : '#ef4444'
  const latencyColor = latency < 2000 ? '#10b981' : latency < 5000 ? '#f59e0b' : '#ef4444'

  // which named agents typically use this tier
  const tierAgents = {
    reasoning: ['PlanningAgent', 'DeveloperAgent', 'DebuggingAgent'],
    fast:      ['EvaluatorAgent', 'TestingAgent'],
  }
  const usedBy = tierAgents[tier] || []

  return (
    <div className="flex-1 p-4 rounded-xl border border-white/10 bg-white/[0.03] hover:border-white/20 transition-all space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div>
          <div className="text-sm font-bold text-slate-100">{meta.label}</div>
          <div className="text-xs font-mono" style={{ color: meta.color }}>{modelName}</div>
        </div>
      </div>

      {/* Token bar */}
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-slate-500">Token share</span>
          <span className="font-mono text-slate-300">{tokens.toLocaleString()} ({pct}%)</span>
        </div>
        <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-700"
            style={{ width: `${pct}%`, background: meta.color }} />
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-black/20 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-slate-200">{calls.toLocaleString()}</div>
          <div className="text-slate-500">total calls</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2 text-center">
          <div className="text-lg font-bold" style={{ color: successColor }}>{success}%</div>
          <div className="text-slate-500">success rate</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2 text-center">
          <div className="text-lg font-bold" style={{ color: latencyColor }}>
            {latency >= 1000 ? `${(latency/1000).toFixed(1)}s` : `${Math.round(latency)}ms`}
          </div>
          <div className="text-slate-500">avg latency</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2 text-center">
          <div className="text-lg font-bold" style={{ color: failed > 0 ? '#ef4444' : '#10b981' }}>
            {failed}
          </div>
          <div className="text-slate-500">failed calls</div>
        </div>
      </div>

      {/* Used by */}
      {usedBy.length > 0 && (
        <div>
          <div className="text-xs text-slate-600 mb-1">Used by agents:</div>
          <div className="flex flex-wrap gap-1">
            {usedBy.map(a => (
              <span key={a} className="text-xs px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-slate-400">
                {a.replace('Agent', '')}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function AgentScoreRow({ agent, stats, projectId }) {
  const neo4jScore = agent.avg_score
  const hasRun     = (agent.tasks || 0) > 0

  const scoreColor = !hasRun
    ? '#64748b'
    : neo4jScore >= 8 ? '#10b981'
    : neo4jScore >= 6 ? '#f59e0b'
    : '#ef4444'

  const retryRate  = hasRun && agent.retry_rate ? (agent.retry_rate * 100).toFixed(0) : null
  const llmTokens  = stats?.total_tokens || 0
  const llmCalls   = stats?.total_calls  || 0

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-xl bg-white/[0.03] border border-white/5 hover:border-white/10 transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-200">{agent.key}</div>
          <div className="text-xs text-slate-500 truncate">{agent.role}</div>
          <div className="text-xs text-slate-600 mt-0.5">
            {hasRun
              ? `${agent.tasks} tasks completed`
              : <span className="text-amber-600">Not triggered this run</span>}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-5 flex-shrink-0 text-xs">
        {/* Token usage from LLM log */}
        <div className="text-right hidden sm:block">
          <div className="font-mono text-slate-300">{llmTokens > 0 ? llmTokens.toLocaleString() : '—'}</div>
          <div className="text-slate-600">tokens used</div>
        </div>
        <div className="text-right hidden sm:block">
          <div className="font-mono text-slate-300">{llmCalls > 0 ? llmCalls : '—'}</div>
          <div className="text-slate-600">LLM calls</div>
        </div>

        {/* Quality score from Neo4j */}
        <div className="text-right">
          <div className="font-bold" style={{ color: scoreColor }}>
            {hasRun ? `${neo4jScore?.toFixed(1) || '0.0'}/10` : 'N/A'}
          </div>
          <div className="text-slate-500">quality</div>
        </div>

        {/* Retry rate */}
        <div className="text-right">
          <div className={`font-bold ${retryRate > 0 ? 'text-amber-400' : 'text-slate-500'}`}>
            {retryRate !== null ? `${retryRate}%` : '—'}
          </div>
          <div className="text-slate-500">retries</div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AgentAnalytics({ projectId }) {
  const [data, setData]             = useState(null)
  const [loading, setLoading]       = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchAnalytics = useCallback(async () => {
    setLoading(true)
    try {
      const url = projectId
        ? `/api/analytics/agents?project_id=${projectId}`
        : '/api/analytics/agents'
      const res = await fetch(url)
      if (res.ok) {
        setData(await res.json())
        setLastUpdated(new Date().toLocaleTimeString())
      }
    } catch (e) {
      console.error('Analytics fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchAnalytics()
    const iv = setInterval(fetchAnalytics, 5000)
    return () => clearInterval(iv)
  }, [fetchAnalytics])

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
        <span className="text-4xl animate-pulse">📊</span>
        <p className="text-sm">Loading agent analytics...</p>
      </div>
    )
  }

  const { summary, per_agent = {}, per_model_tier = {}, neo4j_agents = [], most_failed_task_types = [] } = data
  const totalTokens     = summary?.total_tokens_used || 0
  const isProjectScope  = data.scope !== 'global'

  // Build a map of neo4j_agents keyed by agent name for quick lookup
  const neo4jMap = {}
  neo4j_agents.forEach(a => { neo4jMap[a.agent] = a })

  // Model tier entries sorted by token usage
  const tierEntries = Object.entries(per_model_tier).sort((a, b) => b[1].total_tokens - a[1].total_tokens)

  // Named agents not in the NAMED_AGENTS list (e.g. 'unknown' / system)
  const otherAgentEntries = Object.entries(per_agent)
    .filter(([k]) => !NAMED_AGENTS.some(a => a.key === k) && k !== 'unknown')
    .sort((a, b) => b[1].total_tokens - a[1].total_tokens)

  return (
    <div className="flex flex-col h-full overflow-y-auto space-y-5 pr-1">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-base font-semibold text-slate-200 flex items-center gap-2">
            📊 Agent Analytics Dashboard
          </h2>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-slate-500">Scope:</span>
            {isProjectScope ? (
              <span className="text-xs px-2 py-0.5 rounded-full bg-brand-600/20 text-brand-300 border border-brand-600/30">
                🎯 Project: {data.scope?.replace('project:', '') || ''}
              </span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-600/30 text-slate-400 border border-slate-600/30">
                🌍 All Projects (global)
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && <span className="text-xs text-slate-600">Updated {lastUpdated}</span>}
          <button
            onClick={fetchAnalytics}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg text-xs bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all"
          >
            {loading ? '⟳ Refreshing...' : '⟳ Refresh'}
          </button>
        </div>
      </div>

      {/* ── Summary Cards ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 flex-shrink-0 lg:grid-cols-4">
        <StatCard label="Total LLM Calls"    value={summary?.total_llm_calls?.toLocaleString() || '0'} sub="in scope" color="#8b5cf6" />
        <StatCard
          label="Total Tokens Used"
          value={totalTokens > 1000 ? `${(totalTokens / 1000).toFixed(1)}K` : totalTokens.toString()}
          sub="across all agents"
          color="#3b82f6"
        />
        <StatCard
          label="Success Rate"
          value={`${summary?.overall_success_rate_pct || 0}%`}
          sub={`${summary?.total_failed_calls || 0} failures`}
          color={summary?.overall_success_rate_pct >= 80 ? '#10b981' : '#f59e0b'}
        />
        <StatCard label="Active Agents" value={NAMED_AGENTS.length.toString()} sub="in pipeline" color="#06b6d4" />
      </div>

      {/* ── Per-Agent Deep Analysis ───────────────────────────────────────── */}
      <div className="flex-shrink-0">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          🤖 Agent Performance &amp; Token Usage
          <span className="ml-2 text-slate-600 normal-case font-normal">(quality from Neo4j · tokens from LLM log)</span>
        </h3>
        <div className="space-y-2">
          {NAMED_AGENTS.map(agentMeta => {
            const neo4j  = neo4jMap[agentMeta.key] || {}
            const llmStat = per_agent[agentMeta.key] || {}
            return (
              <AgentScoreRow
                key={agentMeta.key}
                agent={{ ...agentMeta, avg_score: neo4j.avg_score, tasks: neo4j.tasks, retry_rate: neo4j.retry_rate }}
                stats={llmStat}
                projectId={projectId}
              />
            )
          })}
        </div>
      </div>

      {/* ── Model Performance Comparison ───────────────────────────────────── */}
      <div className="flex-shrink-0">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          🧠 Model Tier Performance Comparison
          <span className="ml-2 text-slate-600 normal-case font-normal">(Reasoning vs Fast)</span>
        </h3>
        {tierEntries.length === 0 ? (
          <div className="text-center py-6 text-slate-600 text-sm">No LLM calls recorded yet.</div>
        ) : (
          <div className="space-y-3">

            {/* ── Visual token split bars (like the old style) ── */}
            <div className="p-3 rounded-xl bg-white/[0.03] border border-white/5 space-y-2">
              <div className="text-xs text-slate-500 mb-2">Token Distribution</div>
              {['reasoning', 'fast'].map(tier => {
                const meta   = TIER_META[tier] || TIER_META.unknown
                const stats  = per_model_tier[tier] || {}
                const tokens = stats.total_tokens || 0
                const pct    = totalTokens > 0 ? Math.round((tokens / totalTokens) * 100) : 0
                const calls  = stats.total_calls || 0
                return (
                  <div key={tier} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span>{meta.icon}</span>
                        <span className="text-slate-200 font-medium">{meta.label}</span>
                      </div>
                      <div className="flex items-center gap-3 text-slate-400">
                        <span className="font-mono">{tokens.toLocaleString()} tokens</span>
                        <span className="text-slate-600">|</span>
                        <span>{calls} calls</span>
                        <span className="font-bold" style={{ color: meta.color }}>{pct}%</span>
                      </div>
                    </div>
                    <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${pct}%`, background: meta.color }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>

            {/* ── Detailed side-by-side cards ── */}
            <div className="flex gap-3">
              {['reasoning', 'fast'].map(tier => (
                <ModelTierCard
                  key={tier}
                  tier={tier}
                  stats={per_model_tier[tier] || null}
                  totalTokens={totalTokens}
                />
              ))}
            </div>

          </div>
        )}
      </div>


      {/* ── Why DebuggingAgent is N/A ──────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-brand-600/10 border border-brand-600/20 rounded-xl p-4 space-y-2">
        <h3 className="text-xs font-semibold text-brand-400 uppercase tracking-wider">💡 Diagnostic Guide</h3>
        <ul className="text-xs text-slate-400 space-y-1.5">
          <li>• <span className="text-slate-300">DebuggingAgent N/A</span> → It only activates when a task fails. 0 failures = great pipeline!</li>
          <li>• <span className="text-slate-300">Retry rate 0%</span> → All tasks passed on first attempt — this is ideal.</li>
          <li>• <span className="text-slate-300">High token usage by DeveloperAgent</span> → Its code-gen prompts are the largest; expected.</li>
          <li>• <span className="text-slate-300">Low TestingAgent score</span> → Frontend HTML files are skipped (no DOM in Node.js test runner).</li>
          <li>• <span className="text-slate-300">Low success rate (&lt;70%)</span> → API rate limits or JSON parse errors — check LLM logs.</li>
        </ul>
      </div>

    </div>
  )
}
