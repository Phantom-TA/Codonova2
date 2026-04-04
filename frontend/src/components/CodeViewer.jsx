import React, { useState, useEffect } from 'react'
import { Highlight, themes } from 'prism-react-renderer'

function FileTree({ files, selectedFile, onSelect }) {
  // Group by directory
  const groups = {}
  files.forEach(f => {
    const parts = (f.filename || 'root').split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '.'
    if (!groups[dir]) groups[dir] = []
    groups[dir].push(f)
  })

  return (
    <div className="text-xs space-y-1">
      {Object.entries(groups).map(([dir, dirFiles]) => (
        <div key={dir}>
          <div className="text-slate-500 py-1 px-2 font-mono text-[11px] uppercase tracking-wider">
            {dir === '.' ? 'root' : dir}
          </div>
          {dirFiles.map(file => (
            <button
              key={file.id || file.filename}
              onClick={() => onSelect(file)}
              className={`
                w-full text-left px-3 py-1.5 rounded flex items-center gap-2 font-mono
                transition-colors hover:bg-white/5 group
                ${selectedFile?.id === file.id
                  ? 'bg-brand-600/20 text-brand-400 border-l-2 border-brand-500'
                  : 'text-slate-400 hover:text-slate-200'
                }
              `}
            >
              <svg className="w-3.5 h-3.5 flex-shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <span className="truncate">{(file.filename || '').split('/').pop()}</span>
              {file.size > 0 && (
                <span className="text-slate-600 text-[10px] ml-auto flex-shrink-0">
                  {(file.size / 1000).toFixed(1)}k
                </span>
              )}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

export default function CodeViewer({ projectId }) {
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    fetch(`/api/code/${projectId}/files`)
      .then(r => r.json())
      .then(data => {
        setFiles(data || [])
        if (data?.length > 0) setSelectedFile(data[0])
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [projectId])

  const handleCopy = () => {
    if (selectedFile?.code) {
      navigator.clipboard.writeText(selectedFile.code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const getLanguage = (filename = '') => {
    const ext = filename.split('.').pop()
    return { py: 'python', js: 'javascript', ts: 'typescript', jsx: 'jsx', json: 'json', md: 'markdown' }[ext] || 'python'
  }

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-600 text-sm">
        Select a project to view generated code
      </div>
    )
  }

  return (
    <div className="flex h-full gap-3">
      {/* File Tree */}
      <div className="w-52 flex-shrink-0 overflow-y-auto">
        {loading ? (
          <div className="text-slate-500 text-xs p-3">Loading files...</div>
        ) : files.length === 0 ? (
          <div className="text-slate-600 text-xs p-3">No files generated yet</div>
        ) : (
          <FileTree files={files} selectedFile={selectedFile} onSelect={setSelectedFile} />
        )}
      </div>

      {/* Code Pane */}
      <div className="flex-1 flex flex-col min-w-0 rounded-lg overflow-hidden bg-[#0d1117] border border-white/5">
        {selectedFile ? (
          <>
            {/* File header */}
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5 bg-white/[0.02]">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-brand-400">{selectedFile.filename}</span>
                {selectedFile.type && (
                  <span className="text-[10px] text-slate-500 px-1.5 py-0.5 rounded bg-white/5">
                    {selectedFile.type}
                  </span>
                )}
              </div>
              <button
                onClick={handleCopy}
                className="text-xs text-slate-400 hover:text-white transition-colors flex items-center gap-1.5"
              >
                {copied ? (
                  <><span className="text-green-400">✓</span> Copied</>
                ) : (
                  <><svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>Copy</>
                )}
              </button>
            </div>

            {/* Code */}
            <div className="flex-1 overflow-auto code-block">
              {selectedFile.code ? (
                <Highlight
                  theme={themes.nightOwl}
                  code={selectedFile.code}
                  language={getLanguage(selectedFile.filename)}
                >
                  {({ className, style, tokens, getLineProps, getTokenProps }) => (
                    <pre
                      className={className}
                      style={{
                        ...style,
                        background: 'transparent',
                        padding: '16px',
                        margin: 0,
                        fontSize: '12.5px',
                        lineHeight: '1.7',
                      }}
                    >
                      {tokens.map((line, i) => (
                        <div key={i} {...getLineProps({ line })}>
                          <span className="text-slate-600 mr-4 select-none text-[11px] w-6 inline-block text-right">
                            {i + 1}
                          </span>
                          {line.map((token, key) => (
                            <span key={key} {...getTokenProps({ token })} />
                          ))}
                        </div>
                      ))}
                    </pre>
                  )}
                </Highlight>
              ) : (
                <div className="p-4 text-slate-600 text-xs">No code content</div>
              )}
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-600 text-sm">
            Select a file from the tree
          </div>
        )}
      </div>
    </div>
  )
}
