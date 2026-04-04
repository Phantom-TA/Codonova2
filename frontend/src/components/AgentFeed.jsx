import React, { useEffect, useRef, useState } from 'react'

const AGENT_COLORS = {
  PlanningAgent:   { bg: 'rgba(139,92,246,0.15)', border: 'rgba(139,92,246,0.4)', text: '#a78bfa' },
  DeveloperAgent:  { bg: 'rgba(59,130,246,0.15)', border: 'rgba(59,130,246,0.4)', text: '#60a5fa' },
  TestingAgent:    { bg: 'rgba(16,185,129,0.15)', border: 'rgba(16,185,129,0.4)', text: '#34d399' },
  DebuggingAgent:  { bg: 'rgba(239,68,68,0.15)',  border: 'rgba(239,68,68,0.4)',  text: '#f87171' },
  EvaluatorAgent:  { bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.4)', text: '#fbbf24' },
  Pipeline:        { bg: 'rgba(6,182,212,0.15)',  border: 'rgba(6,182,212,0.4)',  text: '#22d3ee' },
  default:         { bg: 'rgba(71,85,105,0.15)',  border: 'rgba(71,85,105,0.4)',  text: '#94a3b8' },
}

const EVENT_ICONS = {
  task_started:       '▶',
  task_done:          '✓',
  task_failed:        '✗',
  pipeline_started:   '🚀',
  project_complete:   '🏁',
  connected:          '🔗',
  heartbeat:          null, // hidden
}

function AgentBadge({ name }) {
  const style = AGENT_COLORS[name] || AGENT_COLORS.default
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full border"
      style={{ background: style.bg, borderColor: style.border, color: style.text }}
    >
      {name || 'System'}
    </span>
  )
}

function StatusBadge({ event }) {
  const config = {
    task_started:    { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa', label: 'Started' },
    task_done:       { bg: 'rgba(16,185,129,0.15)', color: '#34d399', label: 'Done' },
    task_failed:     { bg: 'rgba(239,68,68,0.15)',  color: '#f87171', label: 'Failed' },
    pipeline_started:{ bg: 'rgba(139,92,246,0.15)', color: '#a78bfa', label: 'Pipeline' },
    project_complete:{ bg: 'rgba(16,185,129,0.2)',  color: '#34d399', label: 'Complete!' },
    connected:       { bg: 'rgba(16,185,129,0.1)',  color: '#34d399', label: 'Connected' },
  }[event] || { bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', label: event }

  return (
    <span
      className="text-xs px-2 py-0.5 rounded"
      style={{ background: config.bg, color: config.color }}
    >
      {config.label}
    </span>
  )
}

export default function AgentFeed({ projectId }) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const endRef = useRef()
  const wsRef = useRef()
  const reconnectRef = useRef()

  const connect = () => {
    const wsUrl = projectId
      ? `ws://localhost:8000/ws/progress/${projectId}`
      : 'ws://localhost:8000/ws/progress'

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setError(null)
      }

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.event === 'heartbeat' || data.event === 'pong') return

          setEvents(prev => [{
            id: Date.now() + Math.random(),
            ...data,
            receivedAt: new Date().toLocaleTimeString(),
          }, ...prev].slice(0, 200)) // Keep last 200

        } catch (err) {
          console.warn('WS parse error:', err)
        }
      }

      ws.onclose = () => {
        setConnected(false)
        reconnectRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        setError('WebSocket connection failed')
        setConnected(false)
      }
    } catch (err) {
      setError(String(err))
    }
  }

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [projectId])

  // Auto-scroll to newest (events are prepended, so scroll to top)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`pulse-dot ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-xs text-slate-400">
            {connected ? 'Live' : 'Reconnecting...'}
          </span>
        </div>
        <span className="text-xs text-slate-500">{events.length} events</span>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded p-2 mb-2">
          {error}
        </div>
      )}

      {/* Feed */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        <div ref={endRef} />

        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 gap-2">
            <svg className="w-10 h-10 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <p className="text-xs">Waiting for pipeline events...</p>
          </div>
        ) : (
          events.map(ev => (
            EVENT_ICONS[ev.event] !== null && (
              <div
                key={ev.id}
                className="animate-slide-up flex items-start gap-3 p-3 rounded-lg bg-white/[0.03] border border-white/5 hover:border-white/10 transition-colors"
              >
                <span className="text-xl mt-0.5 flex-shrink-0">
                  {EVENT_ICONS[ev.event] || '·'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <StatusBadge event={ev.event} />
                    {ev.agent && <AgentBadge name={ev.agent} />}
                    {ev.score !== undefined && (
                      <span className={`text-xs font-bold ${
                        ev.score >= 8 ? 'text-green-400' :
                        ev.score >= 6 ? 'text-amber-400' : 'text-red-400'
                      }`}>
                        Score: {ev.score}/10
                      </span>
                    )}
                    {ev.retry !== undefined && (
                      <span className="text-xs text-amber-400">Retry #{ev.retry}</span>
                    )}
                  </div>
                  {ev.task_id && (
                    <p className="text-xs text-slate-400 font-mono truncate">
                      Task: {ev.task_id?.slice(0, 16)}…
                    </p>
                  )}
                  {ev.message && (
                    <p className="text-xs text-slate-300 mt-0.5">{ev.message}</p>
                  )}
                </div>
                <span className="text-xs text-slate-600 flex-shrink-0">{ev.receivedAt}</span>
              </div>
            )
          ))
        )}
      </div>
    </div>
  )
}
