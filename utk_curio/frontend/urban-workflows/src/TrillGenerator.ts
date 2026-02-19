
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

    static intializeProvenance(trill_spec: any){
        // TODO: look for a provenance JSON for the workflow. If it does not exist initialize it. If it exists load the meta and trill versions to memory (ideally they should be on the database)
        // TODO: for now assuming that the user is never loading a trill or provenanceJSON.

        this.latestTrill = trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp;
        this.list_of_trills[trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp] = trill_spec;

        this.provenanceJSON.id = trill_spec.dataflow.provenance_id;
        this.provenanceJSON.nodes.push({
            id: trill_spec.dataflow.name+"_"+trill_spec.dataflow.timestamp,
            label: trill_spec.dataflow.name+" ("+trill_spec.dataflow.timestamp+")",
            timestamp: trill_spec.dataflow.timestamp
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
            timestamp: new_trill.dataflow.timestamp
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
            loadTrillFunction(this.list_of_trills[name]);

        }catch(error){
            console.error("Error switching provenance:", error);
        }


    }

    static generateTrill(nodes: any, edges: any, name: string, task: string = ""){
    
        let trill = {
            dataflow: {
                nodes: [] as any,
                edges: [] as any,
                name: name,
                task,
                timestamp: Date.now(),
                provenance_id: name
            }
        }

        for(const node of nodes){
            let trill_node: any = {};

            trill_node.id = node.data.nodeId;
            trill_node.type = node.type;
            trill_node.x = node.position.x;
            trill_node.y = node.position.y;

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
