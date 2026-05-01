import React, { useEffect, useRef, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

const STATUS_COLORS = {
  PENDING:     '#64748b',
  IN_PROGRESS: '#3b82f6',
  DONE:        '#10b981',
  FAILED:      '#ef4444',
  BLOCKED:     '#f59e0b',
  Feature:     '#8b5cf6',
  CodeModule:  '#06b6d4',
}

const STATUS_GLOW = {
  IN_PROGRESS: 'rgba(59,130,246,0.6)',
  DONE:        'rgba(16,185,129,0.5)',
  FAILED:      'rgba(239,68,68,0.5)',
}

export default function TaskGraph({ projectId, onNodeClick }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [selectedNode, setSelectedNode] = useState(null)
  const [loading, setLoading] = useState(false)
  const fgRef = useRef()

  const fetchGraph = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await fetch(`/api/graph/${projectId}`)
      const data = await res.json()
      // Assign val (size) based on node type
      const nodes = (data.nodes || []).map(n => ({
        ...n,
        val: n.type === 'Feature' ? 8 : n.type === 'CodeModule' ? 4 : 5,
      }))
      setGraphData({ nodes, links: data.links || [] })
    } catch (e) {
      console.error('Graph fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchGraph()
    const interval = setInterval(fetchGraph, 10000)
    return () => clearInterval(interval)
  }, [fetchGraph])

  // Apply custom physics to spread the graph out properly
  useEffect(() => {
    if (fgRef.current) {
      const chargeForce = fgRef.current.d3Force('charge')
      const linkForce = fgRef.current.d3Force('link')
      if (chargeForce) chargeForce.strength(-400)
      if (linkForce) linkForce.distance(80)
    }
  }, [graphData])

  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node)
    if (onNodeClick) onNodeClick(node)
    // Center view on clicked node
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 600)
      fgRef.current.zoom(2.5, 600)
    }
  }, [onNodeClick])

  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const label = node.label || ''
    const fontSize = Math.max(10 / globalScale, 6)
    const color = STATUS_COLORS[node.status] || STATUS_COLORS[node.type] || '#64748b'
    const r = (node.val || 5) * 1.5

    // Glow for active nodes
    const glow = STATUS_GLOW[node.status]
    if (glow) {
      ctx.shadowColor = glow
      ctx.shadowBlur = 15
    }

    // Circle
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    ctx.strokeStyle = selectedNode?.id === node.id ? '#ffffff' : 'rgba(255,255,255,0.1)'
    ctx.lineWidth = selectedNode?.id === node.id ? 2 / globalScale : 0.5 / globalScale
    ctx.stroke()

    ctx.shadowBlur = 0

    // Label
    if (globalScale > 0.8 && label) {
      ctx.font = `${fontSize}px Inter, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = 'rgba(241,245,249,0.9)'
      const truncated = label.length > 20 ? label.slice(0, 18) + '…' : label
      ctx.fillText(truncated, node.x, node.y + r + 2)
    }
  }, [selectedNode])

  const linkColor = useCallback(() => 'rgba(139,92,246,0.3)', [])
  const linkDirectionalArrowLength = 4
  const linkDirectionalArrowRelPos = 1

  return (
    <div className="relative w-full h-full rounded-xl overflow-hidden">
      {loading && (
        <div className="absolute top-3 right-3 z-10 flex items-center gap-2 text-xs text-slate-400">
          <span className="pulse-dot bg-brand-400"></span>
          Refreshing...
        </div>
      )}

      {graphData.nodes.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
          <svg className="w-16 h-16 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
          </svg>
          <p className="text-sm">No graph data — start a pipeline first</p>
        </div>
      ) : (
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => 'replace'}
          linkColor={linkColor}
          linkDirectionalArrowLength={linkDirectionalArrowLength}
          linkDirectionalArrowRelPos={linkDirectionalArrowRelPos}
          linkWidth={0.8}
          backgroundColor="transparent"
          onNodeClick={handleNodeClick}
          cooldownTicks={80}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
        />
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 glass-card p-3 text-xs space-y-1.5">
        {Object.entries(STATUS_COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: color }} />
            <span className="text-slate-400">{key}</span>
          </div>
        ))}
      </div>

      {/* Node detail tooltip */}
      {selectedNode && (
        <div className="absolute top-3 left-3 glass-card p-4 max-w-xs animate-slide-up">
          <div className="flex items-start justify-between gap-4 mb-2">
            <h4 className="font-semibold text-sm text-white">{selectedNode.label}</h4>
            <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-white text-xs">✕</button>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex gap-2">
              <span className="text-slate-400">Type:</span>
              <span className="text-slate-200">{selectedNode.type}</span>
            </div>
            {selectedNode.status && (
              <div className="flex gap-2">
                <span className="text-slate-400">Status:</span>
                <span className={`status-badge status-${(selectedNode.status||'').toLowerCase()}`}>
                  {selectedNode.status}
                </span>
              </div>
            )}
            {selectedNode.priority && (
              <div className="flex gap-2">
                <span className="text-slate-400">Priority:</span>
                <span className="text-slate-200">P{selectedNode.priority}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
