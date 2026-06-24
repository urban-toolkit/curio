import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
import { useState } from 'react'


function fakeIngest(file: File, role: string, nodeId: string) {
  return {
    artifactId: `saStub_${nodeId}_${Date.now}`,
    fileName: file.name,
    artifactRole: role,
    status: 'ready'
  }
}

//todo: create a behavior hook for soft artifact behavior
export const useSoftArtifactBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [role, setRole] = useState("inform");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReturnType<typeof fakeIngest> | null>(null);

  //call outputcallback when it is ingested, put in onIngest function
  const emitOutput = (descriptor: Record<string, unknown>) => {
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
  const onIngest = () => {
    if (!file) return;

    setBusy(true);
    setResult(null);

    //create a timeout to see ingest status
    window.setTimeout(() => {
      const out = fakeIngest(file, role, data.nodeId);
      setResult(out);
      emitOutput({ artifactId: out.artifactId, fileName: out.fileName, artifactRole: out.artifactRole, status: out.status, stub: true });
      setBusy(false);
    }, 400);
  }

  const contentComponent = (
    <>
      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>
          Role:
        </div>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          style={{ width: '100%', padding: '6px 8px' }}
        >
          <option value="inform"> inform </option>
          <option value="explain"> explain </option>
          <option value="transform"> transform </option>
          <option value="expand"> expand </option>
        </select>
        <p style={{ marginTop: 8, fontSize: 11 }}>Selected: {role}</p>
      </div>
      
      <div style={{ margin: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>
          Document:
        </div>
        <input
          type="file"
          accept='.pdf,.txt,.md'
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />

        {file ? (
          <p style={{ marginTop: 6, fontSize: 11 }}>Selected: {file.name}</p>
        ) : (
          <p style={{ marginTop: 6, fontSize: 11, color: '#94a3b8' }}>No file chosen</p>
        )}
      </div>
      
      <div>
        <button
          type="button"
          onClick={onIngest}
          disabled={!file || busy}
          style={{
            marginTop: 12,
            width: '100%',
            padding: '8px 12px',
            border: 'none',
            borderRadius: 8,
            fontWeight: 600,
            cursor: !file || busy ? 'not-allowed' : 'pointer',
            background: !file || busy ? '#e2e8f0' : '#2563eb',
            color: !file || busy ? '#94a3b8' : '#fff',
          }}
        >
          {busy ? 'Ingesting…' : 'Ingest (stub)'}
        </button>

        {result ? (
          <pre style={{ marginTop: 10, fontSize: 10, background: '#f8fafc', padding: 8 }}>
            {JSON.stringify(result, null, 2)}
          </pre>
          ) : null}
        </div>
    </>

  );

  return {
    contentComponent
  };
}