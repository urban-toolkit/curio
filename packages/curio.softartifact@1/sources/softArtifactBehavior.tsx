import { outputOnly } from '../../../utk_curio/frontend/urban-workflows/src/adapters/node';
import { NodeBehaviorData, NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
import React, { useCallback, useEffect, useState } from 'react';

// Reads the session token out of the browser's cookies (looks for a
// cookie named "session_token") so API calls can authenticate.
function getToken(): string | undefined {
  const match = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

// The different "modes" this artifact node can operate in — determines
// what happens to the uploaded document (just pass it through, explain it, etc.)
type softArtifactRole = 'inform' | 'explain' | 'transform' | 'expand';

// for retrieving chunk
type ChunkRow = {
  chunk_id: string;
  kind?: string;
  text?: string;
  page?: number | null;
  speaker?: string | null;
  t_start?: number | null;
};

// Base URL for all softartifact API calls. Falls back to relative path
// if window.curio.backendUrl isn't set (e.g. during SSR or testing).
const API_BASE = `${(typeof window !== 'undefined' && (window as any).curio?.backendUrl) || ''}/api/softartifact`;

// Shape of the persisted state for this node — this is what gets saved
// on the node data so it survives refreshes/reloads.
interface SoftArtifactState{
  artifact_id: string | null,
  role: softArtifactRole,
  sourceFile: string | null,
  mimetype: string | null,
  status: 'empty' | 'ingesting' | 'ready' | 'error',
  errorMessage?: string,
  chunks?: ChunkRow[];
  explanation?: string,                                    // this is for Explain route
  guidance?: string,                                       // this is for Inform route
  suggestions?: Record<string, unknown>                    // this is for Inform route
  proposal?: Record<string, unknown>                       // this is for Transform route
  rationale?: string                                       // this is for Transform route
}

// Extends the generic NodeBehaviorData with this package's specific
// "softArtifact" field, since the base type doesn't know about it.
type softArtifactNodeData = NodeBehaviorData & {
  softArtifact?: SoftArtifactState
}

// Fresh/blank state for a node that has no artifact yet.
function defaultState(): SoftArtifactState{
  return {
    artifact_id: null,
    role: 'inform',
    sourceFile: null,
    mimetype: null,
    status: 'empty' 
  }
}

// Restores state from whatever was previously saved on the node.
// Merges onto defaultState() so any missing/new fields still get
// sensible defaults (e.g. if the shape changed since last save).
function readSaved(data: {softArtifact?: SoftArtifactState}): SoftArtifactState{
  const raw = data.softArtifact;
  if (!raw || typeof raw !== 'object') return defaultState(); //if raw is invalid return default state
  return { ...defaultState(), ...raw };
}

// Produces the human-readable status label shown on the ingest button,
// based on current state and whether we're mid-verification.
function artifactStatusLine(state: SoftArtifactState, verifying: boolean): string {
  if (verifying) return "verifying artifact";

  switch (state.status) {
    case 'empty':
      return state.sourceFile ? "File selected - not ingested" : "No Document here"
    case 'ingesting':
      return "ingesting"
    case 'ready':
      return "Ready"
    case 'error':
      return state.errorMessage ?? "error"
    default:
      return "the state input is incorrect";  
  }
}

// labeling the chunks
// if kind == pdf -> return page {number of page}
// if kind == transcript -> return {speaker name} @ time 
function chunkLabel(c: ChunkRow): string {
  // convert from time in the chunks into actual time
  // put inside here for the readability 
  function fmtTime(sec?: number | null): string {
    if (sec == null || Number.isNaN(sec)) return "?";
    const s = Math.floor(sec);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`;
  }

  if (c.kind === "pdf_page" && c.page != null) return `page ${c.page}`;
  if (c.kind === "transcript_turn")
    return `${c.speaker || "speaker"} @ ${fmtTime(c.t_start)}`;
  return c.chunk_id;
}

// Calls the backend's /explain endpoint for a given artifact, asking it
// to summarize/explain the document (using the default query server-side).
async function explainArtifact(artifact_id: string, sourceFile: string | null, context?: any, top_k = 8) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  }
  // Attach auth token if we have one
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  //use DEFAULT QUERY in the API not here 
  const body: Record<string, unknown> = {
    artifact_id,
    top_k,
    sourceFile
  }

  if (context !== undefined && context !== null) {
    body.context = context
  }

  const res = await fetch(`${API_BASE}/explain`, {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  })

  // Surface a useful error message if the request failed
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || err.hint || `HTTP ${res.status}`);
  }

  return res.json();

}

// Call the backend's /inform endpoint for a given artifact
// to suggest new nodes or guidance using the given artifact 
async function informArtifact(artifact_id: string, sourceFile: string | null, top_k = 8, context?: any) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const body: Record<string, unknown> = {
    artifact_id,
    sourceFile,
    top_k
  }

  if (context !== undefined && context !== null && context !== '') {
    body.context = context;
  }

  const res = await fetch(`${API_BASE}/inform`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body)
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || err.hint || `HTTP ${res.status}`);
  }

  return res.json();
}

// Call the backend's /propose_trill endpoint for a given artifact and context
// if context(dataflow) is none -> suggests a new dataflow
// if there is a context -> suggest edit to the dataflow 
async function proposeTrillArtifact(artifact_id: string, sourceFile: string | null, top_k = 8, role: string, context?: any) {
  //create a json request
  //json request header
  const headers: Record<string, string> = {
    "Content-Type": "application/json"
  }
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  //json request body
  const body: Record<string, unknown> = {
    artifact_id,
    sourceFile,
    top_k,
    role
  }

  if (context !== undefined && context !== null) {
    body.context = context;
  }
  
  //call API endpoint
  const res = await fetch(`${API_BASE}/propose_trill`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body)
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || err.hint || `HTTP ${res.status}`);
  }

  return res.json()
}

// Main hook powering the "soft artifact" node's behavior — handles file
// upload/ingestion, state persistence, health checks, and the "explain" flow.
export const useSoftArtifactBehavior: NodeBehaviorHook = (data, nodeState) => {
  //data doesn't have softArtifact field, therefore extending the package specific field for data (nodeData)
  const nodeData = data as softArtifactNodeData;  

  const [backendUp, setBackendUp] = useState(false);            // is the backend reachable?
  const [state, setState] = useState<SoftArtifactState>(() => readSaved(nodeData)); // persisted artifact state
  const [file, setFile] = useState<File | null>(null);           // currently selected (not yet ingested) file
  const [verifying, setVerifying] = useState(false); //short-lived UI while the GET api get run 
  const [explaining, setExplaining] = useState<boolean>(false);  // true while /explain call is in flight
  const [informing, setInforming] = useState<boolean>(false);  // true while /inform call is in flight
  const [proposing, setProposing] = useState<boolean>(false);  // true while either transform or expand node call is in flight 


  //health API call
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/health`)
        .then((response) => setBackendUp(response.ok))
        .catch(() => setBackendUp(false))
    };
    check(); // run immediately on mount
    const iv = setInterval(check, 60_000); //check health every 60 seconds 
    return () => clearInterval(iv); // stop polling when unmounted
  }, [])

  //for the UI to survive after every refresh  
  // Updates both React state and the underlying node data object in one go,
  // so changes persist even if the component remounts/reloads.
  const persist = (patch: Partial<SoftArtifactState>) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      nodeData.softArtifact = next; 
      return next;
    });
  };

  // Redundant safety net: whenever `state` changes for any reason, make sure
  // nodeData.softArtifact reflects it (in case persist() wasn't the source).
  useEffect(() => {
    nodeData.softArtifact = state;
  },[state])

  //call outputcallback when it is ingested, put in onIngest function
  // Pushes this node's output downstream to connected nodes in the workflow,
  // wrapping the data in Curio's expected JSON output format.
  const emitOutput = (descriptor: object) => {
    const json = {
      dataType: 'dict',   // JSON objects use 'dict' in Curio’s type system
      data: descriptor,
    };

    nodeState.setOutput({
      code: 'success',
      content: JSON.stringify(json, null, 2),   
      outputType: 'JSON',
    });
    
    data.outputCallback?.(data.nodeId, json);
  };

  //persist + emitOutput
  // Called after a successful ingest: saves the returned artifact metadata
  // and forwards it as this node's output.
  const applyArtifactMeta = (out: Record<string, unknown>, role: softArtifactRole) => {
    persist({
      artifact_id: typeof out.artifact_id === 'string' ? out.artifact_id : null,
      sourceFile: typeof out.sourceFile === 'string' ? out.sourceFile : null,
      mimetype: typeof out.mimetype === 'string' ? out.mimetype : null,
      status: 'ready',
      errorMessage: undefined,
    });

    const cached = nodeData.softArtifact?.explanation;

    if (role === 'explain' && cached) {
      emitOutput({...out, role, explanation: cached})
    }
    else {
      emitOutput({ ...out, role });  // downstream Simple View gets JSON again    
    }
  };

  const loadChunks = async (artifact_id: string) => {
    const res = await fetch(`${API_BASE}/artifacts/${artifact_id}/chunks`);
    if (!res.ok) { persist({chunks: undefined}); return; }
    
    const out = await res.json();
    persist({chunks: out.chunks})    
  }
  // Runs the "explain" flow for the current artifact: calls the backend,
  // stores the explanation, and emits it as node output.
  const runExplain = async (artifact_id: string, role: softArtifactRole) => {
    if (role != 'explain' || !artifact_id) return; // only applies to the "explain" role

    setExplaining(true);
    try {
      const context =
        typeof data.getCurrentTrill === "function"
          ? data.getCurrentTrill() :
          undefined
      
      const out = await explainArtifact(artifact_id, state.sourceFile, context);

      persist({ explanation: out.explanation });

      emitOutput({
        artifact_id,
        sourceFile: state.sourceFile,
        mimetype: state.mimetype,
        role: 'explain',
        explanation: out.explanation,
        query: out.query,
        spans: out.spans,
      })
    } catch (e) {
      // Surface any failure as node error state
      persist({
        status: 'error',
        errorMessage: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setExplaining(false);
    }
  };

  // run 'Inform' flow for the current artifact, call the backend
  // emit the output
  const runInform = async (artifact_id: string, role: softArtifactRole) => {
    if (role != 'inform' || !artifact_id) return;

    setInforming(true);
    
    try {
      const context = 
        typeof data.getCurrentTrill === "function" ?
          data.getCurrentTrill() :
          undefined
      
      const out = await informArtifact(artifact_id, state.sourceFile, 8, context);
      
      persist({ guidance: out.guidance, suggestions: out.suggestions });

      emitOutput({
        artifact_id,
        sourceFile: state.sourceFile,
        mimetype: state.mimetype,
        role: 'inform',
        guidance: out.guidance,
        suggestions: out.suggestions
      })
    } catch (e) {
      persist({
        status: 'error',
        errorMessage: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setInforming(false);
    }
  }

  // run propose, either it's transform or expand artifact
  // for now I haven't added context, need to add it  TODO
  const runPropose = async (artifact_id: string, role: softArtifactRole) => {
    if (role !== 'transform' && role !== 'expand') return;

    setProposing(true);
    try {
      const context = 
        typeof data.getCurrentTrill === "function" 
         ? data.getCurrentTrill() :
          undefined
      
      const out = await proposeTrillArtifact(artifact_id, state.sourceFile, 8, role, context);

      persist({ proposal: out.proposal, rationale: out.rationale})
      
      emitOutput({
        artifact_id,
        sourceFile: state.sourceFile,
        mimetype: state.mimetype,
        role: role,
        proposal: out.proposal,
        rationale: out.rationale
      })
    } catch (e) {
        persist({
          status: 'error',
          errorMessage: e instanceof Error ? e.message : String(e),
        });
    } finally {
      setProposing(false);
    }
  }

  //on mount effect, run once when the node is reloaded
  // Verifies with the backend that a previously-saved artifact_id still
  // exists (e.g. after a page refresh). If the backend no longer has it,
  // clears the stale state so the user knows to re-upload.
  useEffect(() => {
    const artifact_id = nodeData.softArtifact?.artifact_id
    if (!artifact_id) {
      // Nothing was previously ingested — nothing to verify, skip the GET
      console.log("soft artifact Id doesn't exist, skip GET")
      return;
    }

    console.log('[soft-artifact] mount: verifying', artifact_id);
    // Guards against updating state after unmount (see earlier explanation)
    let cancelled = false;
    setVerifying(true);

    (async () => {
      try {
        const res = await fetch(`${API_BASE}/artifacts/${encodeURI(artifact_id)}`)
        if (cancelled) return

        // Backend doesn't recognize this artifact anymore — reset to a clean/error state
        if (res.status === 400) {
          persist({artifact_id: null,
              sourceFile: null,
              mimetype: null,
              status: 'ingesting',
              errorMessage: "missing artifact, reupload",
              explanation: undefined,
              guidance: undefined,
              suggestions: undefined,
              proposal: undefined,
              rationale: undefined,
            });
          setFile(null);
          return;
        }

        // Any other non-OK response: bail out silently (no explicit handling)
        if (!res.ok) return;

        const out = await res.json();
        if (cancelled) return;

        const role = nodeData.softArtifact?.role ?? state.role;
        applyArtifactMeta(out, role);
      } catch {
        console.log("verifying unsuccesful with on mount effect softartifact node");
      } finally {
        if (!cancelled) setVerifying(false);
      }

    })();
    
    // Cleanup: mark this effect run as stale if the component unmounts
    return () => { cancelled = true }
  }, [])
  

  //onChange function for ingest button 
  // Uploads the currently selected file to the backend for ingestion,
  // then applies the returned metadata and (if role is "explain") kicks
  // off the explain flow automatically.
  const onIngest = async () => {
    if (!file) return;

    //before any fetch reset everything on the UI
    persist({artifact_id: null,
        sourceFile: null,
        mimetype: null,
        status: 'ingesting',
        errorMessage: undefined,
        explanation: undefined,
        guidance: undefined,
        suggestions: undefined,
        proposal: undefined,
        rationale: undefined,
      });
    //ingesting the using API_BASE/ingest 
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('role', state.role);

      const res = await fetch(`${API_BASE}/ingest`, {
        method: 'POST',
        headers: {},
        body: form
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP  ${res.status}`)
      }

      const out = await res.json();
      const role = (out.role ?? state.role) as softArtifactRole;
      applyArtifactMeta(out, role);

      console.log('[soft-artifact] ingest out:', out);
      console.log('[soft-artifact] role:', out.role ?? state.role, 'artifact_id:', out.artifact_id);
      // Automatically trigger explanation if this node's role is "explain"
      if (role === "explain" && out.artifact_id) {
        await runExplain(out.artifact_id, role);
      }

      // Automatically trigger explanation if this node's role is "inform"
      if (role === "inform" && out.artifact_id) {
        await runInform(out.artifact_id, role);
      }

      if ((role === "transform" || role === "expand") && out.artifact_id) {
        await runPropose(out.artifact_id, role);
      }

      await loadChunks(out.artifact_id);

    } catch (e) {
      persist({
        status: 'error',
        errorMessage: e instanceof Error ? e.message : String(e),
      })
    }
  }

  // Handles selecting/clearing a file in the <input type="file">.
  // Doesn't upload anything yet — just updates local state until "ingest" is clicked.
  const onFile = (file : File | null) => {
    setFile(file);
    if (!file) {
      // File cleared — reset artifact state entirely
      persist({artifact_id: null,
        sourceFile: null,
        mimetype: null,
        status: 'empty',
        errorMessage: undefined,
        explanation: undefined,
        guidance: undefined,
        suggestions: undefined,
        proposal: undefined,
        rationale: undefined,
      });
      return;
    }

    // New file selected — record its name/type but mark as not-yet-ingested
    persist({
      artifact_id: null,
      sourceFile: file.name,
      mimetype: file.type || 'application/octet-stream',
      status: 'empty',
      errorMessage: undefined,
      explanation: undefined,
      guidance: undefined,
      suggestions: undefined,
      proposal: undefined,
      rationale: undefined,
    });
  }

  // Handles changing the selected role (inform/explain/transform/expand)
  const onRole = (next: softArtifactRole) => {
    persist({ role: next });
  }

  // Display-only string reflecting backend health for the UI
  const statusText = backendUp ? "healthy backend" : "backend down";

  // ---- UI ----
  const contentComponent = (
    <>
      <div>
        backends are {statusText}
      </div>

      {/* Role selector dropdown */}
      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>
          Role:
        </div>
        <select
          value={state.role}
          onChange={(e) => onRole(e.target.value as softArtifactRole)}
          style={{ width: '100%', padding: '6px 8px' }}
        >
          <option value="inform"> inform </option>
          <option value="explain"> explain </option>
          <option value="transform"> transform </option>
          <option value="expand"> expand </option>
        </select>
        <p style={{ marginTop: 8, fontSize: 11 }}>Selected: {state.role}</p>
      </div>
      
      {/* File picker */}
      <div style={{ margin: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>
          Document:
        </div>
        <input
          type="file"
          accept='.pdf,.txt,.md'
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />

        {state.sourceFile ? (
          <p style={{ marginTop: 6, fontSize: 11 }}>Selected: {state.sourceFile}</p>
        ) : (
          <p style={{ marginTop: 6, fontSize: 11, color: '#94a3b8' }}>No file chosen</p>
        )}
      </div>
      
      {/* Ingest button — disabled if no file selected, already ingesting, or backend is down */}
      <div>
        <button
          type="button"
          onClick={onIngest}
          disabled={!file || state.status === 'ingesting' || !backendUp}
          style={{
            marginTop: 10,
            width: '50%',
            padding: '8px 12px',
            border: 'none',
            borderRadius: 5,
            fontWeight: 400,
            cursor: !file || state.status === 'ingesting' ? 'not-allowed' : 'pointer',
            background: !file || state.status === 'ingesting' ? '#e2e8f0' : '#2563eb',
            color: !file || state.status === 'ingesting' ? '#94a3b8' : '#fff',
          }}       
        >
          {artifactStatusLine(state, verifying)}
        </button>
      </div>
        
      {state.chunks && state.chunks.length > 0 && (
      <div style={{ marginTop: 10, maxHeight: 180, overflowY: "auto",
                    border: "1px solid #e2e8f0", borderRadius: 6, padding: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#64748b", marginBottom: 6 }}>
          Chunks ({state.chunks.length})
        </div>
          
        {state.chunks.map((c) => (
          <div key={c.chunk_id} style={{ fontSize: 11, marginBottom: 6 }}>
            <div style={{ fontWeight: 600 }}>{chunkLabel(c)}</div>
            <div style={{ color: "#64748b", whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis" }}>
              {(c.text || "").slice(0, 120)}
            </div>
          </div>
        ))}
      </div>
      )}
      
      {/* Explanation output (shown only in "explain" flow) */}
      <div>
        {state.role === 'explain' && explaining ? (
          <p style={{ fontSize: 11, marginTop: 8 }}>Explaining…</p>
        ) : null}
        {state.explanation ? (
          <pre style={{ marginTop: 8, fontSize: 10, background: '#f8fafc', padding: 8, whiteSpace: 'pre-wrap' }}>
            {state.explanation}
          </pre>
        ) : null}
      </div> 

      {/* Informing output (shown only in "inform" flow) */}
      <div>
        {state.role === 'inform' && informing ? (
          <p style={{ fontSize: 11, marginTop: 8 }}>Informing…</p>
        ) : null}


        {state.guidance ? (
          <pre style={{ marginTop: 8, fontSize: 10, background: '#f8fafc', padding: 8, whiteSpace: 'pre-wrap' }}>
            {state.guidance}
          </pre>
        ) : null}

        {state.suggestions ? (
          <pre style={{ marginTop: 8, fontSize: 10, background: '#f8fafc', padding: 8, whiteSpace: 'pre-wrap' }}>
            { JSON.stringify(state.suggestions, null, 2) }
          </pre>
        ) : null}
      </div>
      
      {/* Proposing output (shown only in either "transform" or "Expand" flow) */}
      <div>
        {state.role === 'transform' && proposing ? (
          <p style={{ fontSize: 11, marginTop: 8 }}>Transforming…</p>
        ) : null}

        {state.proposal?.dataflow ? (
          <div>
          <p>{state.rationale}</p>
          <p>Review before applying</p>
            
          <button
            disabled={typeof data.applyProposal !== "function"}
            onClick={() => {
              data.applyProposal?.(state.proposal!.dataflow);              
            }}
          >
            Apply proposal
          </button>
          
          <button
            onClick={() => {
              data.cancelProposal?.();
              persist({ proposal: undefined, rationale: undefined });
            }}
          >
            Cancel
            </button>
            
            <pre style={{ marginTop: 8, fontSize: 10, background: '#f8fafc', padding: 8, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(state.proposal, null, 2)}
            </pre>
        </div>) : null}
      </div>
    </>

  );

  return {
    contentComponent,
    disablePlay: true
  };
}