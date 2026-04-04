import React, { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis
} from 'recharts'

const getScoreColor = (score) => {
  if (score >= 8) return '#10b981'
  if (score >= 6) return '#f59e0b'
  return '#ef4444'
}

const getScoreGradient = (score) => {
  if (score >= 8) return 'from-green-500/20 to-green-500/5'
  if (score >= 6) return 'from-amber-500/20 to-amber-500/5'
  return 'from-red-500/20 to-red-500/5'
}

function ScoreBar({ filename, score, correctness, code_quality, completeness, critique, passed }) {
  const [expanded, setExpanded] = useState(false)
  const shortName = (filename || 'unknown').split('/').pop()
  const color = getScoreColor(score)

  return (
    <div
      className={`rounded-lg p-3 border cursor-pointer transition-all bg-gradient-to-r ${getScoreGradient(score)}`}
      style={{ borderColor: color + '40' }}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-3 mb-2">
        <div
          className="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm"
          style={{ background: color + '20', color }}
        >
          {score}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-xs text-slate-300 truncate">{shortName}</span>
            {passed
              ? <span className="text-[10px] text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded">✓ PASSED</span>
              : <span className="text-[10px] text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded">✗ FAILED</span>
            }
          </div>
          {/* Mini bars */}
          <div className="grid grid-cols-3 gap-1">
            {[['Correct', correctness], ['Quality', code_quality], ['Complete', completeness]].map(([label, val]) => (
              <div key={label}>
                <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
                  <span>{label}</span><span>{val}</span>
                </div>
                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${(val || 0) * 10}%`, background: getScoreColor(val || 0) }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
        <svg
          className={`w-4 h-4 text-slate-500 flex-shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {expanded && critique && (
        <div className="mt-2 pt-2 border-t border-white/5 text-xs text-slate-400 animate-slide-up">
          <p className="font-medium text-slate-300 mb-1">Critique:</p>
          <p className="leading-relaxed">{critique}</p>
        </div>
      )}
    </div>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload?.length) {
    return (
      <div className="glass-card p-3 text-xs">
        <p className="text-slate-300 font-medium mb-1">{label}</p>
        {payload.map(p => (
          <p key={p.name} style={{ color: p.fill }}>{p.name}: {p.value}</p>
        ))}
      </div>
    )
  }
  return null
}

export default function EvalChart({ projectId }) {
  const [evaluations, setEvaluations] = useState([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState('cards') // 'cards' | 'chart'

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    fetch(`/api/evaluations/${projectId}`)
      .then(r => r.json())
      .then(data => setEvaluations(data || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [projectId])

  const chartData = evaluations.map(ev => ({
    name: (ev.filename || '?').split('/').pop().replace('.py', ''),
    Score: ev.score || 0,
    Correctness: ev.correctness || 0,
    Quality: ev.code_quality || 0,
    Completeness: ev.completeness || 0,
  }))

  const avgScore = evaluations.length
    ? (evaluations.reduce((s, e) => s + (e.score || 0), 0) / evaluations.length).toFixed(1)
    : 0
  const passed = evaluations.filter(e => e.passed).length

  if (!projectId) {
    return <div className="flex items-center justify-center h-full text-slate-600 text-sm">Select a project</div>
  }

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Avg Score', value: `${avgScore}/10`, color: getScoreColor(Number(avgScore)) },
          { label: 'Passed', value: `${passed}/${evaluations.length}`, color: '#10b981' },
          { label: 'Failed', value: `${evaluations.length - passed}/${evaluations.length}`, color: '#ef4444' },
        ].map(stat => (
          <div key={stat.label} className="glass-card p-3 text-center">
            <div className="text-xl font-bold mb-0.5" style={{ color: stat.color }}>{stat.value}</div>
            <div className="text-xs text-slate-500">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* View toggle */}
      <div className="flex items-center gap-1 p-1 bg-white/5 rounded-lg w-fit">
        {['cards', 'chart'].map(v => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-all ${
              view === v ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            {v === 'cards' ? '≡ Cards' : '▣ Chart'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center flex-1 text-slate-500 text-sm">Loading evaluations...</div>
      ) : evaluations.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 text-slate-600 gap-2">
          <span className="text-3xl">📊</span>
          <p className="text-sm">No evaluations yet</p>
        </div>
      ) : view === 'cards' ? (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {evaluations.map((ev, i) => (
            <ScoreBar key={i} {...ev} />
          ))}
        </div>
      ) : (
        <div className="flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 50 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis
                dataKey="name"
                tick={{ fill: '#64748b', fontSize: 10 }}
                angle={-30}
                textAnchor="end"
                interval={0}
              />
              <YAxis domain={[0, 10]} tick={{ fill: '#64748b', fontSize: 10 }} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="Score" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i} fill={getScoreColor(entry.Score)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
