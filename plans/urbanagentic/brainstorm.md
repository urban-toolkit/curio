Agents Catalog (customized agents)
Refine an idea:

Look for inspiration on Dribbble and any similar sites

Helpful resources:


Pre-requirements
- From the dataset, expand the full lineage (all upstream nodes that generated it)
- Can nodes have JS, Python, and HTML code nodes for input creation?

Brainstormed ideas
- From questions to datasets(DATA AGENT) and nodes(NODE AGENT) creation
- How to query data in the dataset - query refiner
- How to define hooks

Agent Registering (Superpowers)
- We can register agents to do many things (composition of agents)
- to search the web
- to look at a PDF document
- to document/explain a workflow
- RAG/Agent constructor

List of agents
- Como incorporar agents na interface atual ui (similar to the data/node catalog)
- Management and creation of different prompts
- Como o user vai criar e compartilhar?
- De uma maneira simples talvez alguns agentes predefinidos

Customization of the agent (Installation and Editing)
- Canvas and Chat Synchronization
- Como o agente vai lidar com os dataflows
- Como definir a ação do agente

Constraints (TBD)
- tokens

Data Agent
- Connect with external databases (the database preview can show where the dataset is coming from)
    - The connection will be through the node that gets the data from an external database
       Select datasets based on user questions
    - The user makes a question?
    - Then the system suggests?

Node Agent

- HTML node for widget creation
- Leave the connections independent of the nodes? Redesign node relations in the palette
- Começar com uma localização ?
- Node: passive (data nodes) and active (that transform or perform computation)?

————
Ideas for an AGENT of agents (Agent Constructor)(Agent templating similar to node templates)

I want to add a feature similar to nodes and data catalog but for agents, like a magic wand that, when accessed, 
can suggest urban goals/missions that will be generated and managed by those agents or RAGS to reach those goals.

Agent Mission: Agent Constructor to suggest agents to work on urban analysis:

How to describe/create a new agent
- List this agent
- Brief description of what the agent does - brief description
- Number of steps (agent actions)
- Every action description and details

QUESTIONS

How to use the best ux illustrate the composition of multiple predefined (or not; they can be created) agents to construct other agents?

Does it make sense, or does agentic AI already involve creating or spiking custom agents like the superpowers (https://claude.com/plugins/superpowers)?

Tasks/Project/workflows Examples:

- Load and Clean
- Geospatial Join + Visualize
- Compute Statistics + Chart
- Time-series Exploration
- Build a Dashboard


Base agents/prompts

"chat_prompt",
"debug_prompt",
"explanation_prompt",
"single_box_explanation_prompt",
"new_content_prompt",
"new_subtask_from_exec_prompt",
"new_subtasks_prompt",
"new_connection_prompt",
"workflow_suggestions_prompt",
"evaluate_coherence_subtasks_prompt",
"evaluate_generated_content_prompt",
"syntax_analysis_prompt",
"task_refresh_prompt",
"keywords_binding_prompt"


- Can they be transformed into custom composable agents/tasks to reach a greater task?
(in the code the llmRequest(" is scattered through the code). 
- We need to create an encapsulated module for LLM/agentic calls/requests

Say when the workflow came from a dataset
VIZ IDEAS

- planetary or atom viz
- periodic table viz
- Resemble a birds nest

——————

Like the creation of the suggested projects:

Here are 3 long-term innovative urban analytics project ideas that could fit well into Curio:

1. Urban Mobility Intelligence Layer
Build a system that analyzes how people, vehicles, bikes, transit, and pedestrians move through the city over time. It could combine GTFS transit data, traffic counts, bike lane usage, crash data, weather, events, and land use patterns.
Possible features:
* Detect mobility bottlenecks by time of day and season
* Compare transit access across neighborhoods
* Predict where bike/pedestrian infrastructure would have the highest impact
* Simulate effects of road diets, new bus routes, or development projects
* Create equity-focused mobility scores for different communities
Why it fits Curio: it would turn fragmented transportation datasets into a decision-support tool for planners, researchers, and civic groups.

1. Neighborhood Change and Displacement Early Warning System
Create an analytics platform that tracks signals of neighborhood transformation before displacement pressures become severe. It could analyze housing prices, permits, evictions, tax assessments, business turnover, demographic change, short-term rentals, transit investment, and public infrastructure projects.
Possible features:
* Longitudinal neighborhood change dashboards
* Displacement risk index by census tract or parcel cluster
* Alerts when multiple pressure indicators rise together
* Scenario analysis for zoning or redevelopment proposals
* Community-facing explanations of what is changing and why
Why it fits Curio: it would make urban change more legible and help cities act earlier instead of only reacting after communities are already under pressure.

1. Urban Climate Resilience Digital Twin
Develop a city-scale analytics model that helps understand climate risks across neighborhoods, especially heat, flooding, tree canopy, impervious surfaces, air quality, and vulnerable populations.
Possible features:
* Heat vulnerability maps combining temperature, shade, age, income, and health indicators
* Flood-risk analytics using terrain, stormwater infrastructure, rainfall, and land cover
* Tree canopy and cooling intervention prioritization
* “What if” simulations for green roofs, permeable pavement, parks, or street trees
* Resilience investment scorecards by neighborhood
Why it fits Curio: it would connect physical infrastructure, environmental data, and social vulnerability into one planning tool for climate adaptation.
A strong Curio framing could be: “from urban data exploration to urban decision intelligence.” These projects would let Curio move beyond dashboards into predictive, scenario-based, and equity-aware analytics.



INSPIRATIONS

https://claude.com/plugins/superpowers

https://makeabilitylab.cs.washington.edu/project/geovisally/

Users can toggle focus between map and chat using Ctrl + M . Upon focusing on the chat, GeoVisA11y announces, “Type your question here, press Enter to submit.” After submission, the system repeats the user query followed by a status indicator (“Looking for answers...”).

—————

- Sketches (dribbble)
- For the agent catalog and your sketches, we will probably need to define the interface "hooks" that the agents can latch onto
- We should probably have a way to use open models as well, so we don't waste so many tokens. 

Main Inspiration Video
/Users/karla/coding/curio-feat/plans/urbanagentic/Screen Recording 20260629 at 31522 PM 1.mp4
----------

AGENT - Dataflow creation: /Users/karla/coding/curio-feat/plans/urbanagentic/dataflow-creator/dataflow-creator-agent.md
----------

“Loop engineering” is a hot buzzphrase after mentions of it by Boris Cherny (Claude Code’s creator) and Peter Steinberger (OpenClaw's creator) went viral on social media. Loops are now a key part of how we get AI agents to iterate at length to build software. In this letter, I’d like to share my 3 key loops, shown in the image below, for building 0-to-1 products. These loops guide not just how I build software, but also how I decide what software to build.

Agentic coding loop: Given a product specification and optionally a set of evals (that is, a dataset against which to measure performance), we can have an AI agent write code, test its work, and keep iterating until the code is bug-free and meets its specification. This idea of closing the loop took off around the end of last year, and it has been a game changer in enabling coding agents to work longer productively without human intervention. For example, over the weekend, I was building an app for my daughter to practice typing, and my coding agent could easily work for around an hour, using a web browser to check what it had built multiple times before getting back to me, without needing my intervention.

The engineering loop executes quickly. Every few minutes, the coding agent might build and test a new version of the software. I hear frequently from developers who are finding new ways to engineer more effective engineering loops. This is an active area of invention!

Developer feedback loop: In this loop, a developer examines the current product and steers the coding agent to improve it. Last year, a lot of developers (including me) were acting as the QA (quality assurance) function for our coding agents, manually finding bugs and then asking the agent to fix them. But with coding agents much more able to test their own code, the amount of time we need to spend on this function has decreased significantly. This allows us to make higher-level product decisions, such as what key features to offer, where the UI needs improvement, and so on.

The developer-feedback loop operates over time intervals between tens of minutes and hours — that's how frequently a developer might review a product and give feedback. In the case of the typing app, I changed my mind a few times about the visual design, what cat costumes she can unlock as she learns (she loves cats), and the user flow for a grown-up to log in and steer the child's learning experience.

When a developer has a clear vision for what to build, it is still a lot of work to translate that vision into a specification for a coding agent to implement. Further, after the developer has seen an implementation, they might update (or perhaps clarify) the spec to steer it toward what they want. If you find that the system repeatedly runs into certain problems, building a set of evals for the agent becomes useful.

AI-native teams are increasingly using AI to help shape product direction, for example, automating the gathering and analysis of usage data, summarizing written and verbal customer feedback, or carrying out competitive analysis. However, for pretty much all the products I’m involved in, I see humans as having a significant context advantage over current AI systems — we know a lot more than the AI system about the users and the context the product has to operate in — and thus humans play a critical role. Many people describe this human contribution as “taste,” but I prefer to think of it as humans having a context advantage, since that gives us a clearer path to helping AI systems get better. This also speaks to why this step can’t be automated: So long as the human knows something the AI does not, human-in-the-loop is needed to to inject that knowledge into the system.

External feedback loop: This includes a wide range of tactics like asking a few friends for feedback, launching to alpha testers, or putting the code into production with A/B testing. These tactics are usually slow, rarely taking less than hours and sometimes taking days or even weeks. This data informs the developer vision, which in turn continues to drive the detailed product spec, which in turn drives the coding agent.

With coding agents speeding up software development, more engineers are starting to play a partial product management role. For many engineers who are growing into this role, the hardest part is shaping the product vision and striking a balance between building (bridging the gap between vision and spec) and getting user feedback to evolve the vision. It is important to do both!

I will write more about how to do this in future posts, but for now, I find it encouraging that engineers are playing an expanded role (just as product managers and designers now do more engineering).

[Original text: The Batch]