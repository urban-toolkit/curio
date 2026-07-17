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

// Base URL for all softartifact API calls. Falls back to relative path
// if window.curio.backendUrl isn't set (e.g. during SSR or testing).
const API_BASE = `${(typeof window !== 'undefined' && (window as any).curio?.backendUrl) || ''}/api/softartifact`;

// Shape of the persisted state for this node — this is what gets saved
// on the node data so it survives refreshes/reloads.
interface SoftArtifactState{
  artifactId: string | null,
  role: softArtifactRole,
  sourceFile: string | null,
  mimeType: string | null,
  status: 'empty' | 'ingesting' | 'ready' | 'error',
  errorMessage?: string,
  explanation?: string,                                    // this is for Explain route
  guidance?: string,                                       //this is for Inform route
  suggestions?: Record<string, unknown>                    //this is for Inform route
  proposal?: Record<string, unknown>                       //this is for Transform route
  rationale?: string                                       //this is for Transform route
}

// Extends the generic NodeBehaviorData with this package's specific
// "softArtifact" field, since the base type doesn't know about it.
type softArtifactNodeData = NodeBehaviorData & {
  softArtifact?: SoftArtifactState
}

// Fresh/blank state for a node that has no artifact yet.
function defaultState(): SoftArtifactState{
  return {
    artifactId: null,
    role: 'inform',
    sourceFile: null,
    mimeType: null,
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

// Calls the backend's /explain endpoint for a given artifact, asking it
// to summarize/explain the document (using the default query server-side).
async function explainArtifact(artifactId: string, sourceFile: string | null, top_k = 8) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  }
  // Attach auth token if we have one
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(`${API_BASE}/explain`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      artifactId: artifactId,
      top_k: top_k,
      sourceFile: sourceFile
      //No query, use Default query
    })
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
async function informArtifact(artifactId: string, sourceFile: string | null, top_k = 8, context?: string) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const body: Record<string, unknown> = {
    artifactId,
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
async function proposeTrillArtifact(artifactId: string, sourceFile: string | null, top_k = 8, mode: string, context?: any) {
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
    artifactId,
    sourceFile,
    top_k,
    mode
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
  const [proposing, setProposing] = useState<boolean>(false);


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
      artifactId: typeof out.artifactId === 'string' ? out.artifactId : null,
      sourceFile: typeof out.sourceFile === 'string' ? out.sourceFile : null,
      mimeType: typeof out.mimeType === 'string' ? out.mimeType : null,
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

  // Runs the "explain" flow for the current artifact: calls the backend,
  // stores the explanation, and emits it as node output.
  const runExplain = async (artifactId: string, role: softArtifactRole) => {
    if (role != 'explain' || !artifactId) return; // only applies to the "explain" role

    setExplaining(true);
    try {
      const out = await explainArtifact(artifactId, state.sourceFile);

      persist({ explanation: out.explanation });

      emitOutput({
        artifactId,
        sourceFile: state.sourceFile,
        mimeType: state.mimeType,
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
  const runInform = async (artifactId: string, role: softArtifactRole) => {
    if (role != 'inform' || !artifactId) return;

    setInforming(true);
    
    try {
      const out = await informArtifact(artifactId, state.sourceFile);
      
      persist({ guidance: out.guidance, suggestions: out.suggestions });

      emitOutput({
        artifactId,
        sourceFile: state.sourceFile,
        mimeType: state.mimeType,
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
  const runPropose = async (artifactId: string, role: softArtifactRole) => {
    if (role !== 'transform' && role !== 'expand') return;

    setProposing(true);
    try {
      const context = 
        typeof data.getCurrentTrill === "function" 
         ? data.getCurrentTrill() :
          undefined
      
      const out = await proposeTrillArtifact(artifactId, state.sourceFile, 8, role, context);

      persist({ proposal: out.proposal, rationale: out.rationale })
      
      emitOutput({
        artifactId,
        sourceFile: state.sourceFile,
        mimeType: state.mimeType,
        role: 'propose',
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
  // Verifies with the backend that a previously-saved artifactId still
  // exists (e.g. after a page refresh). If the backend no longer has it,
  // clears the stale state so the user knows to re-upload.
  useEffect(() => {
    const artifactId = nodeData.softArtifact?.artifactId
    if (!artifactId) {
      // Nothing was previously ingested — nothing to verify, skip the GET
      console.log("soft artifact Id doesn't exist, skip GET")
      return;
    }

    console.log('[soft-artifact] mount: verifying', artifactId);
    // Guards against updating state after unmount (see earlier explanation)
    let cancelled = false;
    setVerifying(true);

    (async () => {
      try {
        const res = await fetch(`${API_BASE}/artifacts/${encodeURI(artifactId)}`)
        if (cancelled) return

        // Backend doesn't recognize this artifact anymore — reset to a clean/error state
        if (res.status === 400) {
          persist({
            artifactId: null,           // clear stale id — backend doesn't have it
            sourceFile: null,           // optional: clear or keep for context
            mimeType: null,
            status: 'error',
            errorMessage: 'artifact missing — re-upload',
            explanation: undefined
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
    persist({artifactId: null,
        sourceFile: null,
        mimeType: null,
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
      console.log('[soft-artifact] role:', out.role ?? state.role, 'artifactId:', out.artifactId);
      // Automatically trigger explanation if this node's role is "explain"
      if (role === "explain" && out.artifactId) {
        await runExplain(out.artifactId, role);
      }

      // Automatically trigger explanation if this node's role is "inform"
      if (role === "inform" && out.artifactId) {
        await runInform(out.artifactId, role);
      }

      if (role === "transform" && out.artifactId) {
        await runPropose(out.artifactId, role)
      }

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
      persist({artifactId: null,
        sourceFile: null,
        mimeType: null,
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
      artifactId: null,
      sourceFile: file.name,
      mimeType: file.type || 'application/octet-stream',
      status: 'empty'
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