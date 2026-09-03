/**
 * Serializes the canvas into a Trill dataflow document, and keeps its version
 * history.
 *
 * The output format's canonical spec is `docs/schemas/trill.v1.json`; the prose
 * reference is `docs/TRILL-SPEC.md`. Adding a field here means declaring it
 * there - `TestDeclaredKeyCoverage` in
 * `backend/tests/test_projects/test_trill_schema.py` fails on a field the
 * examples use and the schema does not document, because the schema is
 * deliberately open and would otherwise accept it in silence.
 *
 * `loadTrill` in `hook/useCode.ts` is the matching reader.
 */
export class TrillGenerator {

    static provenanceJSON: any = {
        id: "",
        nodes: [],
        edges: []
    };

    static latestTrill: string = "";

    static list_of_trills: any = {}; // [workflowName_timestamp] -> trill_spec

    static reset() {
        this.provenanceJSON = { id: "", nodes: [], edges: [] };
        this.latestTrill = "";
        this.list_of_trills = {};
    }

    static _extractGraphPreview(trill: any): { nodes: any[]; edges: any[] } {
        const nodes = (trill.dataflow?.nodes || []).map((n: any) => ({
            id: n.id,
            type: n.type,
            x: n.x ?? 0,
            y: n.y ?? 0,
            w: n.width ?? null,
            h: n.height ?? null,
        }));
        const edges = (trill.dataflow?.edges || []).map((e: any) => ({
            source: e.source,
            target: e.target,
        }));
        return { nodes, edges };
    }

    /** A version key that is not already taken.
     *
     * The base is `<name>_<timestamp>`, which is what saved specs contain and
     * what `provenanceGraphNode.id` documents. That is not unique: the timestamp
     * has millisecond resolution and a single gesture can record more than one
     * version inside one millisecond. When it collided, several versions
     * collapsed onto one `versions` key, the graph grew duplicate node ids and
     * self-loop edges, and React reported two children with the same key — with
     * the real consequence that the provenance graph could silently drop or
     * duplicate a version. Committed projects on disk already contain this.
     *
     * A suffix keeps the format a plain string and a usable `versions` key, so
     * older files (whose ids never carry one) keep loading untouched.
     */
    private static _uniqueVersionId(name: string, timestamp: number): string {
        const base = `${name}_${timestamp}`;
        if (this.list_of_trills[base] === undefined) return base;
        let n = 2;
        while (this.list_of_trills[`${base}_${n}`] !== undefined) n += 1;
        return `${base}_${n}`;
    }

    static intializeProvenance(trill_spec: any){
        // TODO: look for a provenance JSON for the workflow. If it does not exist initialize it. If it exists load the meta and trill versions to memory (ideally they should be on the database)
        // TODO: for now assuming that the user is never loading a trill or provenanceJSON.

        const versionId = this._uniqueVersionId(
            trill_spec.dataflow.name, trill_spec.dataflow.timestamp,
        );
        this.latestTrill = versionId;
        this.list_of_trills[versionId] = trill_spec;

        this.provenanceJSON.id = trill_spec.dataflow.provenance_id;
        this.provenanceJSON.nodes.push({
            id: versionId,
            label: trill_spec.dataflow.name+" ("+trill_spec.dataflow.timestamp+")",
            timestamp: trill_spec.dataflow.timestamp,
            preview: this._extractGraphPreview(trill_spec)
        });
    }

    static addNewVersionProvenance(nodes: any, edges: any, name: string, task: string, change: string){

        console.log("nodes", [...nodes]);

        console.log("adding new provenance version for Trill");

        let new_trill = this.generateTrill(nodes, edges, name, task);
        
        console.log("new_trill", new_trill);

        const versionId = this._uniqueVersionId(
            new_trill.dataflow.name, new_trill.dataflow.timestamp,
        );

        this.provenanceJSON.nodes.push({
            id: versionId,
            label: new_trill.dataflow.name+" ("+new_trill.dataflow.timestamp+")",
            timestamp: new_trill.dataflow.timestamp,
            preview: this._extractGraphPreview(new_trill)
        });

        this.list_of_trills[versionId] = new_trill;

        // An edge from a version to itself carries no history and duplicates an
        // existing key, which is how a colliding id showed up as a React
        // duplicate-key warning in the provenance graph.
        if(this.latestTrill && this.latestTrill !== versionId){
            this.provenanceJSON.edges.push({
                id: this.latestTrill+"_to_"+versionId,
                source: this.latestTrill,
                target: versionId,
                label: change
            })
        }

        this.latestTrill = versionId;

    }

    static switchProvenanceTrill(name: string, loadTrillFunction: any){

        try{

            if(this.list_of_trills[name] == undefined)
                throw new Error("Non existant trill: "+name);

            this.latestTrill = name;
            loadTrillFunction(this.list_of_trills[name], undefined, true);

        }catch(error){
            console.error("Error switching provenance:", error);
        }


    }

    static getSerializableDataflowProvenance(): any {
        return {
            id: TrillGenerator.provenanceJSON.id,
            latest: TrillGenerator.latestTrill,
            graph: TrillGenerator.provenanceJSON,
            versions: TrillGenerator.list_of_trills,
        };
    }

    static loadDataflowProvenance(data: any): void {
        if (!data) return;
        TrillGenerator.provenanceJSON = data.graph || { id: "", nodes: [], edges: [] };
        TrillGenerator.latestTrill = data.latest || "";
        TrillGenerator.list_of_trills = data.versions || {};
    }

    static generateTrill(nodes: any, edges: any, name: string, task: string = "", packages: string[] = [], description: string = "", datasets: any[] = []){

        let trill: any = {
            dataflow: {
                nodes: [] as any,
                edges: [] as any,
                name: name,
                task,
                timestamp: Date.now(),
                provenance_id: name,
                packages,
            }
        }
        if (description) {
            trill.dataflow.description = description;
        }

        const datasetRefs = new Map<string, any>();
        for (const dataset of datasets || []) {
            const id = dataset?.datasetId || dataset?.id;
            if (id) datasetRefs.set(id, dataset);
        }

        for(const node of nodes){
            let trill_node: any = {};

            trill_node.id = node.data.nodeId;
            // Persist dispatcher id (`data.nodeType`); RF `type` stays a sentinel for all UniversalNode-backed templates.
            trill_node.type = node.data?.nodeType ?? node.type;

            // Use workflow position so saving in dashboard mode doesn't corrupt the layout
            const workflowPos = node.data.workflowPosition ?? node.position;
            trill_node.x = workflowPos.x;
            trill_node.y = workflowPos.y;

            if(typeof node.data.nodeWidth === "number")
                trill_node.width = node.data.nodeWidth;

            if(typeof node.data.nodeHeight === "number")
                trill_node.height = node.data.nodeHeight;

            if(node.data.dashboardPinned)
                trill_node.dashboardPinned = true;

            if(typeof node.data.dashboardX === "number"){
                trill_node.dashboardX = node.data.dashboardX;
                trill_node.dashboardY = node.data.dashboardY;
            }

            if(typeof node.data.dashboardWidth === "number"){
                trill_node.dashboardWidth = node.data.dashboardWidth;
                trill_node.dashboardHeight = node.data.dashboardHeight;
            }

            if(typeof node.data.saveOutputDataset === "boolean")
                trill_node.saveOutputDataset = node.data.saveOutputDataset;

            if(node.data.code != undefined){
                trill_node.content = node.data.code;
            }

            if(node.data.out != undefined)
                trill_node.out = node.data.out;
            
            if(node.data.in != undefined)
                trill_node.in = node.data.in;

            if(node.data.goal != undefined)
                trill_node.goal = node.data.goal;

            if(node.data.keywords != undefined){
                if(trill_node.metadata == undefined)
                    trill_node.metadata = {};

                trill_node.metadata.keywords = node.data.keywords;
            }

            if(Array.isArray(node.data.datasetRefs) && node.data.datasetRefs.length > 0){
                if(trill_node.metadata == undefined)
                    trill_node.metadata = {};

                trill_node.metadata.datasetRefs = node.data.datasetRefs;
            }

            if(node.data.datasetSource != undefined && node.data.datasetSource.datasetId != undefined){
                if(trill_node.metadata == undefined)
                    trill_node.metadata = {};

                trill_node.metadata.datasetSource = node.data.datasetSource;
            }

            // dev/89: per-node appearance persists at the canonical
            // metadata.appearance shape — without this, a recolored post-it
            // would lose its color on the next canvas save.
            if(node.data.appearance != undefined && node.data.appearance.backgroundColor != undefined){
                if(trill_node.metadata == undefined)
                    trill_node.metadata = {};

                trill_node.metadata.appearance = node.data.appearance;
            }

            // #237: per-node comments persist at metadata.comments, beside
            // appearance/keywords. Emitted only when non-empty, so a node
            // nobody commented on serializes byte-identically to before.
            if(Array.isArray(node.data.comments) && node.data.comments.length > 0){
                if(trill_node.metadata == undefined)
                    trill_node.metadata = {};

                trill_node.metadata.comments = node.data.comments;
            }

            if(typeof node.data.title === "string" && node.data.title)
                trill_node.title = node.data.title;

            if(node.data.appliedDatasets != undefined){
                for(const dataset of Object.values(node.data.appliedDatasets)){
                    const id = (dataset as any)?.datasetId || (dataset as any)?.id;
                    if(id && !datasetRefs.has(id))
                        datasetRefs.set(id, dataset);
                }
            }

            trill.dataflow.nodes.push(trill_node)
        }

        if(datasetRefs.size > 0){
            trill.dataflow.datasets = Array.from(datasetRefs.values());
        }

        for(const edge of edges){
            let trill_edge: any = {};

            if(edge.type == "BIDIRECTIONAL_EDGE"){ // This is an interaction edge
                trill_edge.type = "Interaction"
            }

            trill_edge.id = edge.id;
            trill_edge.source = edge.source;
            trill_edge.target = edge.target;

            // Persist the concrete handles. Slot wiring (`in_N` on merge
            // nodes) must not depend on loadTrill's edge-id heuristic —
            // agent-built edges have plain UUID ids, so without these fields
            // their slot assignment is lost and they reload as unrenderable
            // `"in"` edges (dev/64). Omitted when absent to keep specs lean.
            if (edge.sourceHandle) trill_edge.sourceHandle = edge.sourceHandle;
            if (edge.targetHandle) trill_edge.targetHandle = edge.targetHandle;

            if(edge.data != undefined && edge.data.keywords != undefined){
                if(trill_edge.metadata == undefined)
                    trill_edge.metadata = {};

                trill_edge.metadata.keywords = edge.data.keywords;
            }

            trill.dataflow.edges.push(trill_edge);
        }

        return trill
    
    }

}
