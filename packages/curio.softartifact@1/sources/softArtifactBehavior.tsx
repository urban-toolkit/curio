	
import { NodeBehaviorData, NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
import React, { useEffect, useState } from 'react'

type softArtifactRole = 'inform' | 'explain' | 'transform' | 'expand';

interface SoftArtifactState{
  artifactId: string | null,
  role: softArtifactRole,
  sourceFile: string | null,
  mimeType: string | null,
  status: 'empty' | 'ingesting' | 'ready' | 'error',
  errorMessage?: string
}

//package specific field saved on node
type softArtifactNodeData = NodeBehaviorData & {
  softArtifact?: SoftArtifactState
}

function defaultState(): SoftArtifactState{
  return {
    artifactId: null,
    role: 'inform',
    sourceFile: null,
    mimeType: null,
    status: 'empty' 
  }
}

function readSaved(data: {softArtifact?: SoftArtifactState}): SoftArtifactState{
  const raw = data.softArtifact;
  if (!raw || typeof raw !== 'object') return defaultState(); //if raw is invalid return default state
  return { ...defaultState(), ...raw };
}


const API_BASE = `${(typeof window !== 'undefined' && (window as any).curio?.backendUrl) || ''}/api/softartifact`;

//todo: create a behavior hook for soft artifact behavior
export const useSoftArtifactBehavior: NodeBehaviorHook = (data, nodeState) => {
  //health API
  const [backendUp, setBackendUp] = useState(false);
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/health`)
        .then((response) => setBackendUp(response.ok))
        .catch(() => setBackendUp(false))
    };
    check();
    const iv = setInterval(check, 10_000); //check health every 10 seconds 
    return () => clearInterval(iv);
  }, [])

  const [file, setFile] = useState<File | null>(null);

  //data doesn't have softArtifact field, therefore extending the package specific field for data (nodeData)
  const nodeData = data as softArtifactNodeData;  
  const [state, setState] = useState<SoftArtifactState>(() => readSaved(nodeData));
  //for the UI to survive after every refresh  
  const persist = (patch: Partial<SoftArtifactState>) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      nodeData.softArtifact = next; 
      return next;
    });
  };

  useEffect(() => {
    nodeData.softArtifact = state;
  },[state])

  //call outputcallback when it is ingested, put in onIngest function
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

  //onChange function for ingest button 
  const onIngest = async () => {
    if (!file) return;

    persist({ status: "ingesting" });

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
        throw new Error(err.Error || `HTTP  ${res.status}`)
      }

      const out = await res.json();
      persist({
        artifactId: out.artifactId,
        role: out.role ?? state.role,
        sourceFile: out.sourceFile,
        mimeType: out.mimeType,
        status: 'ready',
      })

      emitOutput({ ...out });
      
    } catch (e) {
      persist({
        status: 'error',
        errorMessage: e instanceof Error ? e.message : String(e),
      })
    }
  }

  const onFile = (file : File | null) => {
    setFile(file);
    if (!file) {
      persist(defaultState());
      return;
    }
    persist({
      artifactId: null,
      sourceFile: file.name,
      mimeType: file.type || 'application/octet-stream',
      status: 'empty'
    })
  }

  const onRole = (next: softArtifactRole) => {
    persist({ role: next });
  }

  const statusText = backendUp ? "healthy af" : "sad af";

  const contentComponent = (
    <>
      <div>
        backends are {statusText}
      </div>

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
          {state.status === 'ingesting' ? 'Ingesting…' : 'Ingest (stub)'}
        </button>

        {state ? (
          <pre style={{ marginTop: 10, fontSize: 10, background: '#f8fafc', padding: 8 }}>
            {JSON.stringify(state, null, 2)}
          </pre>
          ) : null}
      </div>
    </>

  );

  return {
    contentComponent,
    disablePlay: true
  };
}