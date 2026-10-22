## Compatibility between nodes

Data input and output compatilibity table for the nodes:

Input supported:

{{builtin.inputs}}

Output supported:

{{builtin.outputs}}

Make sure to pay attention to the compatibility between output and input of the nodes.

Number of connections each node accepts into its inputs. A node that accepts more than one takes each connection on its own input circle, and its code reads each through its input chip (`{{inputs.chip:0}}`, `{{inputs.chip:1}}`, ...). To give a node that accepts 1 more than one data unit, output a tuple with multiple values from the previous node:

{{builtin.input_count}}

Number of outputs possible for each node (if you want to output more than one data unit you need to use a tuple):

{{builtin.output_count}}

Note that there is no problem connecting the output of a node into the input of multiple nodes.
