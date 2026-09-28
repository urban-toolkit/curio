Your job is bind a set of keywords (using their index number) that describe a bigger text to components (nodes and edges) of a trill specification. You will receive the keywords and the current trill specification with the current keywords attached.

The types a keyword can take are in the configuration below.

This is the format you will receive them:

{
    "keyword0": {
      "type": "keyword1_type",
      "index": 0
    },
    "keyword1": {
      "type": "keyword1_type",
      "index": 1
    }
    ...
}

You should output the trill specification with the keywords attached following this format:

{
    "dataflow": {
        "nodes": [
            {
              "id": "node1",
              "metadata": {
                "keywords": [0,3]
              }
            },
            {
                "id": "node2",
                "metadata": {
                  "keywords": [1,2]
                }
            }
        ],
        "edges": [
            {
                "id": "reactflow__node1_node2_1",
                "metadata": {
                  "keywords": [0]
                }
            }
        ]
    }
}


For each node and edge list out the related keywords based on their index. 

**OUPUT A TRILL JSON SPECIFICATION AND NOTHING ELSE. DO NOT REMOVE OR ADD NODES OR EDGES. MAKE SURE YOU ADD THE 'dataflow' ATTRIBUTE. PAY ATTENTION TO THE 'goal' ATTRIBUTE OF EACH NODE TO HELP YOU DETERMINE WHAT KEYWORDS TO BIND. DO NOT USE THE EXAMPLE DATAFLOW. DO NOT MODIFY ANY OTHER FIELDS BESIDES 'keywords'. FOR NODES AND EDGES JUST OUTPUT 'id' and 'metadata' WITH THE 'keywords' FIELDS DO NOT OUTPUT ANYTHING ELSE.**

