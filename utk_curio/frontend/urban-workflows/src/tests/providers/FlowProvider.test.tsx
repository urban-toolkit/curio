/**
 * this is for individual functions testing
 * testings the whole dataflow require E2E testing which is not this
 */

import React from "react";
import { renderHook, act } from '@testing-library/react';
import { NodeType, ResolutionType } from '../../constants';


/**Heavy depenecencies mocking and will change as the test file gets bigger*/

/**reactFlow mock 
 * toDo: comment here 
 * 
 */
let mockInitialNode: any[] = [];
let mockEdges: any[] = [];

jest.mock('reactflow', () => {
  const actualReact = require('react');
  return {
    useNodesState: () => {
      const [nodes, setNodes] = actualReact.useState(mockInitialNode);
      return [nodes, setNodes, jest.fn()];
    },
    useEdgesState: () => {
      const [edges, setEdges] = actualReact.useState(mockEdges);
      return [edges, setEdges, jest.fn()];
    },
    useReactFlow: () => ({  
      getNodes: () => mockInitialNode,
      getEdges: () => mockEdges,
      getNode: (id: any) => mockInitialNode.find((n: any) => n.id == id)
    }),
    addEdge: jest.fn((edge, edges) => [...edges, edge]),
    getOutgoers: () => [],
    MarkerType: { ArrowClosed: 'arrowclosed' },
  }
});

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() })
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    enabled: false,
    onRemote: jest.fn(() => jest.fn()),
    broadcastNodeAdded: jest.fn(),
    broadcastNodeRemoved: jest.fn(),
    broadcastEdgeAdded: jest.fn(),
    broadcastEdgeRemoved: jest.fn()
  }),
}));

jest.mock('../../ConnectionValidator', () => ({
  ConnectionValidator: {
    checkBoxCompatibility: (outNode: any, inNode: any) => true,
  },
}));


jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn()
  }),
}));

jest.mock('../../hook/useCode', () => ({
  pythonInterpreter: {},
  jsInterpreter: {},
}));

import FlowProvider, { useFlowContext } from "../../providers/FlowProvider";

//create a html element like </FlowProvider> {children} <FlowProvider>
const wrapper = ({ children }: { children: React.ReactNode }) => 
  React.createElement(FlowProvider, null, children)


//helper function, make a node  with the type computation analysis
const makeNode = (id: string, extraData: any = {}) => ({
  id,
  type: "__curioUniversalNode",
  position: { x: 0, y: 0 },
  data: {
    nodeId: id, nodeType: "curio.builtin/computation-analysis@1", ...extraData
  }
});

//helper function, make a merge Node
const makeMergeNode = (id: string, extraData: any = {}) => ({
  id,
  type: '__curioUniversalNode',
  position: { x: 0, y: 0 },
  data: {
    nodeId: id,
    nodeType: NodeType.MERGE_FLOW,
    ...extraData,
  },
});

//make a single edge between source and target,
const makeEdge = (source: string, target: string, sourceHandle = 'out', targetHandle = 'in_0') => ({
  id: `${source}-${target}`,
  source,
  target,
  sourceHandle,
  targetHandle,
});


//helper function, make a linear chain a -> b -> c
const makeLinearChain = () => {
  mockInitialNode = [makeNode('a'), makeNode('b'), makeNode('c')];
  mockEdges = [makeEdge('a', 'b'), makeEdge('b', 'c')]
}

describe('FlowProviderTest', () => {
  //refresh the nodes and edges after each test
  beforeEach(() => {
    mockInitialNode = [];   // keys for each node: {id position data}
    mockEdges = [];         // keys for each edge: {id source target sourceHandle targetHandle}
  })
  describe('testing onConnect function', () => {
    /**
     *  create two connection:  a->merge and b->merge
     * checking if mergeNode.data.source has both node on it 
     */
    it('onConnect simple test, make sure that mergeNode.data.source has two nodes connected to it', () => {
      mockInitialNode = [
        makeNode('a'),
        makeNode('b'),
        makeMergeNode('merge'),
      ];

      mockEdges = [];

      const { result } = renderHook(() => useFlowContext(), { wrapper });

      act(() => {
        result.current.onConnect({
          source: 'a',
          target: 'merge',
          sourceHandle: 'out',
          targetHandle: 'in_0',
        } as any);
      });
      
      let mergeNode = result.current.nodes.find((node: any) => node.id === 'merge');

      expect(mergeNode?.data.source?.[0]).toBe('a');

      act(() => {
        result.current.onConnect({
          source: 'b',
          target: 'merge',
          sourceHandle: 'out',
          targetHandle: 'in_1',
        } as any);
      });

      mergeNode = result.current.nodes.find((node: any) => node.id === 'merge');
      console.log(mergeNode?.data);
      expect(mergeNode?.data.source?.[1]).toBe('b');
    });
  })

  describe('testing playAllNodes function', () => {
    it('playAllNodes trigger the first node exec only', () => {
      makeLinearChain(); // a -> b -> c
      
      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.playAllNodes() });

      const nodeA = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');

      expect(nodeA?.data.triggerExec).toBe(1);
      expect(nodeB?.data.triggerExec ?? 0).toBe(0);
    })

    it('playAllNodes trigger the first node and advances to the next level of node', () => {
      makeLinearChain();  // a -> b -> c

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.playAllNodes(); });
      act(() => { result.current.signalNodeExecDone('a'); });  //the first node is done now move to the second node
      
      const nodeA = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');
      
      expect(nodeA?.data.triggerExec).toBe(1);
      expect(nodeB?.data.triggerExec).toBe(1);
    })

    it('playAllNodes guard against playAllStateRef', () => {
      makeLinearChain(); // a -> b -> c
      
      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.playAllNodes() });

      const triggerAfterFirst = result.current.nodes.find((node: any) => node.id == 'a');
      act(() => { result.current.playAllNodes() });
      const triggerAfterSecond = result.current.nodes.find((node: any) => node.id == 'a');

      expect(triggerAfterSecond).toBe(triggerAfterFirst); 
    })

    it('does not trigger nodes on an empty canvas', () => {
      mockInitialNode = [];
      mockEdges = [];
      const { result } = renderHook(() => useFlowContext(), { wrapper });

      // Should not throw
      expect(() => {
        act(() => { result.current.playAllNodes(); });
      }).not.toThrow();
    });
    
    it('clear after the last level complete', () => {
      mockInitialNode = [makeNode('onlyNode')];
      mockEdges = [];

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.playAllNodes() });
      act(() => { result.current.signalNodeExecDone('onlyNode') });
      act(() => { result.current.playAllNodes() });
      //now the second playAllNodes should be playable
      //the onlyNode.triggerExec should be = 2
      const onlyNode = result.current.nodes.find((node: any) => node.id == 'onlyNode');
      expect(onlyNode?.data.triggerExec).toBe(2);
    })
  })


  describe('playNodesUpTo', () => {

    // sanity test for playNodesUpTo function
    it('triggers only the ancestors and the target node, not unrelated nodes', () => {
      // a -> b -> c    and standalone d
      mockInitialNode = [makeNode('a'), makeNode('b'), makeNode('c'), makeNode('d')];
      mockEdges = [
        makeEdge('a','b') ,
        makeEdge('b', 'c')
      ];

      const { result } = renderHook(() => useFlowContext(), { wrapper });

      act(() => { result.current.playNodesUpTo('c'); });

      const nodeA = result.current.nodes.find((n: any) => n.id === 'a');
      const nodeD = result.current.nodes.find((n: any) => n.id === 'd');

      // a is an ancestor of c — should be triggered
      expect(nodeA?.data.triggerExec).toBeGreaterThan(0);
      // d is unrelated — must NOT be triggered
      expect(nodeD?.data.triggerExec ?? 0).toBe(0);
    });

    //during playAllNodes state, playNodesUpTo shouldn't play
    //playNodesUpTo also shouldnt overwrite the ref

    it('playNodesUpTo does nothing while playAllNode is playing', () => {
      makeLinearChain(); // a -> b -> c
      const { result } = renderHook(() => useFlowContext(), { wrapper });

      act(() => result.current.playAllNodes());
      const nodeA_before_playNodesUpTo = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB_before_playNodesUpTo = result.current.nodes.find((node: any) => node.id == 'b');

      act(() => result.current.playNodesUpTo('c'));
      const nodeA_after_playNodesUpTo = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB_after_playNodesUpTo = result.current.nodes.find((node: any) => node.id == 'b');

      expect(nodeA_after_playNodesUpTo).toBe(nodeA_after_playNodesUpTo);
      expect(nodeB_after_playNodesUpTo).toBe(nodeB_after_playNodesUpTo);
    })
  
});


  //applyNewOutput takes an { nodeId, output } parameter, finds downstream nodes via edges, and sets their data.input
  describe('testing ApplyNewOutput function', () => {
    //testing if it actually send output downstream
    //making a -> b edge, test if b.data.input == a.data.output and b.data.source == a after calling applyNewOutput
    //also testing if the 'b' data is overwritten
    //standalone c node shouldn't have receive any downstream input
    it('ApplyNewOutput send data downstream', () => {
      //create a->b edge
      mockEdges = [makeEdge('a', 'b')]
      //create a, b, c nodes
      mockInitialNode = [
        makeNode('a'),
        makeNode('b', { label: 'python computation', source: 'initial source', input: 'initial input' }),
        makeNode('c', { nodeType: 'javascript' }),
      ]

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: "artifact-sample" }); })

      const nodeA = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');
      const nodeC = result.current.nodes.find((node: any) => node.id == 'c')

      expect(nodeA?.data.input).toBeUndefined();
      
      //nodeA send data downstream to nodeB
      expect(nodeB?.data.input).toBe('artifact-sample');
      expect(nodeB?.data.source).toBe('a');
      expect(nodeB?.data.label).toBe('python computation');

      expect(nodeC?.data.input).toBeUndefined();
      expect(nodeC?.data.source).toBeUndefined();
      expect(nodeC?.data.nodeType).toBe('javascript');
    });
    //a->b edge and a->c edge and a standalone d node
    //testing if when a send data downstream to correct nodes (b and c)
    it('ApplyNewOutput send data to the correct nodes', () => {
      mockEdges = [
        makeEdge('a', 'b'),
        makeEdge('a', 'c', 'out_1', 'in_1'),
      ]
      mockInitialNode = [
        makeNode('a'),
        makeNode('b', { label: 'python computation', nodeType: 'python' }),
        makeNode('c', { nodeType: 'javascript' }),
        makeNode('d', { nodeType: 'C++' }),
      ]

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: "artifact sample" }); })

      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');
      const nodeC = result.current.nodes.find((node: any) => node.id == 'c');
      const nodeD = result.current.nodes.find((node: any) => node.id == 'd');

      expect(nodeB?.data.input).toBe("artifact sample");
      expect(nodeB?.data.source).toBe("a");
      expect(nodeB?.data.label).toBe("python computation");
      expect(nodeB?.data.nodeType).toBe("python");

      expect(nodeC?.data.input).toBe("artifact sample");
      expect(nodeC?.data.source).toBe("a");
      expect(nodeC?.data.nodeType).toBe("javascript");

      expect(nodeD?.data.input).toBeUndefined();
      expect(nodeD?.data.source).toBeUndefined();
      expect(nodeD?.data.nodeType).toBe('C++');
    })
    //no downstream edges
    it('ApplyNewOutput node isnt connected to any node', () => {
      mockInitialNode = [
        makeNode('a'),
        makeNode('b', { label: 'python computation', nodeType: 'python' }),
      ];
      mockEdges = [];

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: "artifact sample" }); })
      
      const nodeA = result.current.nodes.find((node: any) => node.id == 'a');
      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');
      
      expect(nodeB?.data.input).toBeUndefined();
      expect(nodeB?.data.source).toBeUndefined();
      expect(nodeB?.data.nodeType).toBe('python');

      expect(nodeA?.data.input).toBeUndefined();
    })

    //the data beng sent downstream is undefined
    it('ApplyNewOutput with undefined output', () => {
      mockInitialNode = [
        makeNode('a'),
        makeNode('b', { label: 'python computation', nodeType: 'python' }),
      ];
      mockEdges = [makeEdge('a', 'b', 'out_0', 'in_0')];

      const { result } = renderHook(() => useFlowContext(), { wrapper });
      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: undefined as any }); })

      const nodeB = result.current.nodes.find((node: any) => node.id == 'b');
  
      expect(nodeB?.data.source).toBe('');
      expect(nodeB?.data.input).toBe('');
    })

    //mergeFlow node will receive multiple input
    //a -> mergeNode   and   b -> mergeNode
    //expected: mergeNode.data have both data from 'a' node and 'b' node
    //geuinely don't know if the data.source and data.input should be initlaized before applyNewOutput?
    //problem with onConnect have to check it 
    it('two nodes connected to mergeNode', () => {
      mockInitialNode = [
        makeNode('a'),
        makeNode('b'),
        makeMergeNode('merge', { source: ['a', 'b'] }),
      ];

      mockEdges = [
        makeEdge('a', 'merge', 'out', 'in_0'),
        makeEdge('b', 'merge', 'out', 'in_1'),
      ];

      const { result } = renderHook(() => useFlowContext(), { wrapper });

      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: "nodeAOutput" }); });
      
      act(() => { result.current.applyNewOutput({ nodeId: 'b', output: "nodeBOutput"}); });

      const mergeNode = result.current.nodes.find((node: any) => node.id === 'merge');

      console.log(mergeNode?.data);
      expect(mergeNode?.data.source[0]).toEqual('a');
      expect(mergeNode?.data.source[1]).toEqual('b');
      expect(mergeNode?.data.input[0]).toEqual("nodeAOutput");
      expect(mergeNode?.data.input[1]).toBe('nodeBOutput');
    });

    //mergeFlow node receive two inputs and output to one node
    //a -> merge,  b -> merge,   merge -> c 
    //expected: c node has data of both a and b node 
    it('merge node propagate output to downstream node c', () => {
      mockInitialNode = [
        makeNode('a'),
        makeNode('b'),
        makeMergeNode('merge', { source: ['a', 'b'] }),
        makeNode('c'),
      ];

      mockEdges = [
        makeEdge('a', 'merge', 'out', 'in_0'),
        makeEdge('b', 'merge', 'out', 'in_1'),
        makeEdge('merge', 'c'),
      ];

      const { result } = renderHook(() => useFlowContext(), { wrapper });

      act(() => { result.current.applyNewOutput({ nodeId: 'a', output: 'outputFromA' }); });
      act(() => { result.current.applyNewOutput({ nodeId: 'b', output: 'outputFromB' }); });
      act(() => { result.current.applyNewOutput({ nodeId: 'merge', output: 'outputFromMerge?' }); });

      const nodeC = result.current.nodes.find((n: any) => n.id === 'c');
      const nodeMerge = result.current.nodes.find((n: any) => n.id === 'merge');

      // Merge received both inputs — this should pass
      expect(nodeMerge?.data.input[0]).toBe('outputFromA');
      expect(nodeMerge?.data.input[1]).toBe('outputFromB');

      expect(nodeC?.data.input).toBeDefined();   
      expect(nodeC?.data.source).toBe('merge');  
    });
  })
})