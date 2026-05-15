
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

    static intializeProvenance(trill_spec: any){
        // TODO: look for a provenance JSON for the workflow. If it does not exist initialize it. If it exists load the meta and trill versions to memory (ideally they should be on the database)
        // TODO: for now assuming that the user is never loading a trill or provenanceJSON.

        this.latestTrill = trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp;
        this.list_of_trills[trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp] = trill_spec;

        this.provenanceJSON.id = trill_spec.dataflow.provenance_id;
        this.provenanceJSON.nodes.push({
            id: trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp,
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

        this.provenanceJSON.nodes.push({
            id: new_trill.dataflow.name+"_"+new_trill.dataflow.timestamp,
            label: new_trill.dataflow.name+" ("+new_trill.dataflow.timestamp+")",
            timestamp: new_trill.dataflow.timestamp,
            preview: this._extractGraphPreview(new_trill)
        });

        this.list_of_trills[new_trill.dataflow.name+"_"+new_trill.dataflow.timestamp] = new_trill;

        console.log("list_of_trills", this.list_of_trills);

        if(this.latestTrill){ // If there is a previous trill from which this one was derived add an edge connecting both
            this.provenanceJSON.edges.push({        
                id: this.latestTrill+"_to_"+new_trill.dataflow.name+"_"+new_trill.dataflow.timestamp,
                source: this.latestTrill,
                target: new_trill.dataflow.name+"_"+new_trill.dataflow.timestamp,
                label: change
            })
        }

        this.latestTrill = new_trill.dataflow.name+"_"+new_trill.dataflow.timestamp;

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

    static generateTrill(nodes: any, edges: any, name: string, task: string = "", packages: string[] = [], description: string = ""){

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

        for(const node of nodes){
            let trill_node: any = {};

            trill_node.id = node.data.nodeId;
            // Persist dispatcher id (`data.nodeType`); RF `type` stays a sentinel for all UniversalNode-backed kinds.
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

            trill.dataflow.nodes.push(trill_node)
        }

        for(const edge of edges){
            let trill_edge: any = {};

            if(edge.type == "BIDIRECTIONAL_EDGE"){ // This is an interaction edge
                trill_edge.type = "Interaction"
            }

            trill_edge.id = edge.id;
            trill_edge.source = edge.source;
            trill_edge.target = edge.target;

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
