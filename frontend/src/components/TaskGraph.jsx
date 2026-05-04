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
  BLOCKED:     'rgba(245,158,11,0.4)',
}

export default function TaskGraph({ projectId, onNodeClick }) {
  // graphData only changes when node/link COUNT changes — not on status updates
  const [graphData, setGraphData]       = useState({ nodes: [], links: [] })
  const [selectedNode, setSelectedNode] = useState(null)
  const [loading, setLoading]           = useState(false)
  const [simStopped, setSimStopped]     = useState(false)
  const [statusCounts, setStatusCounts] = useState({})

  const fgRef          = useRef()
  const liveStatus     = useRef({})   // { [nodeId]: status } — updated without re-render
  const nodePositions  = useRef({})
  const graphDataRef   = useRef({ nodes: [], links: [] })
  const initialised    = useRef(false)
  const zoomTimer      = useRef(null)

  // ── Merge: only call setGraphData when structure changes ─────────────────
  const mergeGraphData = useCallback((newData) => {
    const newNodes = newData.nodes || []
    const newLinks = newData.links || []

    // ALWAYS update the live status map (used by canvas painter)
    newNodes.forEach(n => { liveStatus.current[n.id] = n.status })

    // Compute counts for UI badges (cheap — no re-render of ForceGraph)
    const counts = {}
    newNodes.forEach(n => {
      const s = n.status || n.type
      counts[s] = (counts[s] || 0) + 1
    })
    setStatusCounts(counts)

    const existing    = graphDataRef.current
    const countChanged =
      newNodes.length !== existing.nodes.length ||
      newLinks.length !== existing.links.length

    if (!initialised.current || countChanged) {
      // Full structural reset — this triggers ForceGraph2D to remount simulation
      const nodes = newNodes.map(n => ({
        ...n,
        val: n.type === 'Feature' ? 8 : n.type === 'CodeModule' ? 4 : 5,
        ...(nodePositions.current[n.id] || {}),
      }))
      const next = { nodes, links: newLinks }
      graphDataRef.current = next
      initialised.current = true
      setSimStopped(false)
      setGraphData(next)

      // Zoom-to-fit after simulation settles
      clearTimeout(zoomTimer.current)
      zoomTimer.current = setTimeout(() => {
        fgRef.current?.zoomToFit(700, 60)
      }, 4000)
      return
    }

    // STATUS-ONLY UPDATE — mutate existing node objects directly.
    // ForceGraph2D's canvas loop reads node properties every animation frame,
    // so color changes appear automatically. No setGraphData = no sim restart.
    const nodeMap = {}
    graphDataRef.current.nodes.forEach(n => { nodeMap[n.id] = n })
    newNodes.forEach(n => {
      if (nodeMap[n.id]) nodeMap[n.id].status = n.status
    })
  }, [])

  // ── Fetch ────────────────────────────────────────────────────────────────
  const fetchGraph = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res  = await fetch(`/api/graph/${projectId}`)
      const data = await res.json()
      mergeGraphData(data)
    } catch (e) {
      console.error('Graph fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [projectId, mergeGraphData])

  // Reset everything on project change
  useEffect(() => {
    initialised.current  = false
    liveStatus.current   = {}
    nodePositions.current = {}
    clearTimeout(zoomTimer.current)
    setSimStopped(false)
    setSelectedNode(null)
    setStatusCounts({})
    const empty = { nodes: [], links: [] }
    graphDataRef.current = empty
    setGraphData(empty)
    fetchGraph()
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 4 s (no harm since status updates don't restart simulation)
  useEffect(() => {
    const id = setInterval(fetchGraph, 4000)
    return () => clearInterval(id)
  }, [fetchGraph])

  // Apply physics once when nodes first appear
  const hasNodes = graphData.nodes.length > 0
  useEffect(() => {
    if (!fgRef.current || !hasNodes) return
    const fg     = fgRef.current
    const charge = fg.d3Force('charge')
    const link   = fg.d3Force('link')
    if (charge) charge.strength(-420)
    if (link)   link.distance(95)
  }, [hasNodes])

  // Pin nodes + zoom when simulation naturally stops
  const handleEngineStop = useCallback(() => {
    if (!fgRef.current) return
    // graphData() is NOT a method on react-force-graph-2d — use our own ref instead
    graphDataRef.current.nodes.forEach(n => {
      if (n.x !== undefined) {
        n.fx = n.x;  n.fy = n.y
        nodePositions.current[n.id] = { x: n.x, y: n.y, fx: n.x, fy: n.y }
      }
    })
    clearTimeout(zoomTimer.current)
    fgRef.current.zoomToFit(700, 60)
    setSimStopped(true)
  }, [])

  const handleNodeDragEnd = useCallback(node => {
    node.fx = node.x;  node.fy = node.y
    nodePositions.current[node.id] = { x: node.x, y: node.y, fx: node.x, fy: node.y }
  }, [])

  const handleNodeRightClick = useCallback(node => {
    node.fx = undefined;  node.fy = undefined
  }, [])

  const handleNodeClick = useCallback(node => {
    setSelectedNode(node)
    if (onNodeClick) onNodeClick(node)
    fgRef.current?.centerAt(node.x, node.y, 600)
    fgRef.current?.zoom(2.5, 600)
  }, [onNodeClick])

  // Canvas painter — reads from liveStatus ref so NO re-render needed for color changes
  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const status  = liveStatus.current[node.id] || node.status
    const color   = STATUS_COLORS[status] || STATUS_COLORS[node.type] || '#64748b'
    const glow    = STATUS_GLOW[status]
    const r       = (node.val || 5) * 1.5
    const label   = node.label || ''
    const fontSize = Math.max(10 / globalScale, 6)

    if (glow) { ctx.shadowColor = glow;  ctx.shadowBlur = 15 }
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    ctx.strokeStyle = selectedNode?.id === node.id ? '#ffffff' : 'rgba(255,255,255,0.1)'
    ctx.lineWidth   = selectedNode?.id === node.id ? 2 / globalScale : 0.5 / globalScale
    ctx.stroke()
    ctx.shadowBlur  = 0

    if (globalScale > 0.8 && label) {
      ctx.font         = `${fontSize}px Inter, sans-serif`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle    = 'rgba(241,245,249,0.9)'
      ctx.fillText(label.length > 20 ? label.slice(0, 18) + '…' : label, node.x, node.y + r + 2)
    }
  }, [selectedNode])

  const inProgressNodes = graphData.nodes.filter(n =>
    (liveStatus.current[n.id] || n.status) === 'IN_PROGRESS'
  )
  const failedNodes = graphData.nodes.filter(n =>
    (liveStatus.current[n.id] || n.status) === 'FAILED'
  )

  return (
    <div className="relative w-full h-full rounded-xl overflow-hidden">

      {/* Top bar */}
      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-3 pointer-events-none">
        {inProgressNodes.length > 0 && (
          <div className="glass-card px-4 py-1.5 flex items-center gap-2 border-blue-500/30">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500" />
            </span>
            <span className="text-xs font-medium text-blue-100">
              {inProgressNodes.map(n => n.label).join(', ')}
            </span>
          </div>
        )}
        {loading && (
          <div className="glass-card px-3 py-1 text-xs text-slate-500 flex items-center gap-1.5">
            <span className="pulse-dot bg-brand-400" /> Syncing...
          </div>
        )}

      </div>

      {!hasNodes ? (
        <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
          <svg className="w-16 h-16 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1}
              d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
          </svg>
          <p className="text-sm">No graph data — start a pipeline first</p>
        </div>
      ) : (
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => 'replace'}
          linkColor={() => 'rgba(139,92,246,0.3)'}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkWidth={0.8}
          backgroundColor="transparent"
          onNodeClick={handleNodeClick}
          onNodeDragEnd={handleNodeDragEnd}
          onNodeRightClick={handleNodeRightClick}
          onEngineStop={handleEngineStop}
          cooldownTicks={200}
          cooldownTime={6000}
          d3AlphaDecay={0.025}
          d3VelocityDecay={0.45}
        />
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 glass-card p-3 text-xs space-y-1.5">
        {Object.entries(STATUS_COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: color }} />
            <span className="text-slate-400">
              {key}
              {statusCounts[key] > 0 && (
                <span className="ml-1 opacity-60">({statusCounts[key]})</span>
              )}
            </span>
          </div>
        ))}
      </div>

      {/* Node tooltip */}
      {selectedNode && (
        <div className="absolute top-3 right-3 glass-card p-4 max-w-xs animate-slide-up z-20">
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
              <div className="flex gap-2 items-center">
                <span className="text-slate-400">Status:</span>
                <span className={`status-badge status-${(liveStatus.current[selectedNode.id] || selectedNode.status || '').toLowerCase()}`}>
                  {liveStatus.current[selectedNode.id] || selectedNode.status}
                </span>
              </div>
            )}
            {(liveStatus.current[selectedNode.id] || selectedNode.status) === 'BLOCKED' && (
              <p className="text-amber-400/80 text-[10px] mt-1">⚠ Blocked — a dependency failed</p>
            )}
            {(liveStatus.current[selectedNode.id] || selectedNode.status) === 'PENDING' && (
              <p className="text-slate-500 text-[10px] mt-1">ℹ Not executed — pipeline ended with errors</p>
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

      {/* Failed panel */}
      {failedNodes.length > 0 && (
        <div className="absolute bottom-16 right-3 max-w-sm glass-card p-4 border-red-500/30 z-10">
          <div className="flex items-center gap-2 mb-2 border-b border-red-500/20 pb-2">
            <span className="text-red-400">⚠️</span>
            <h3 className="font-semibold text-sm text-red-100">Failed ({failedNodes.length})</h3>
          </div>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {failedNodes.map(node => (
              <div key={node.id}
                className="bg-red-500/10 border border-red-500/20 rounded-lg p-2 cursor-pointer hover:bg-red-500/20 transition-colors"
                onClick={() => handleNodeClick(node)}
              >
                <div className="text-xs font-semibold text-red-200">{node.label}</div>
                <div className="text-[10px] text-red-400/70 mt-0.5">FAILED · blocked {statusCounts['BLOCKED'] || 0} downstream task(s)</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
