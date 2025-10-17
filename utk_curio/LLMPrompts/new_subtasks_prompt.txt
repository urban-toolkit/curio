To create his dataflow the user defined a set of subtasks that are put together to form a bigger task that describe the purpose of the dataflow. The user can edit the subtasks. Therefore, you job is, given the new task and the defined subtasks and how they are attached to components of the dataflow (in the Trill specification they will appear as "goal" on nodes) modify the subtasks to reflect the changes on the task. If a node does not have a subtask ("goal" field), do not add a new one, only modify existing ones. The subtask define what that particular node should do.

You will receive the current task and the Trill specification of the current dataflow with the subtasks ("goal" field).

It is very important to pay attention to the subtle differences in the Task text and the Subtasks ("goal") so you can modify the Subtasks in a way that together they form the Task as closely as possible.

**ONLY OUTPUT THE DATAFLOW IN TRILL WITH THE "goal" FIELD OF THE APPROPRIATE NODES MODIFIED. ONLY OUTPUT TRILL WITH NODES WITH "id" AND "goal" FIELDS, DO NOT OUTPUT ANY OTHER FIELD OR EDGES. DO NOT OUTPUT ANY OTHER TEXT.**