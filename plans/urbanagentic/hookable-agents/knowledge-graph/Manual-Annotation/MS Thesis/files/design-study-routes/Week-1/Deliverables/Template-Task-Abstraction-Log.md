## Purpose
Use this template to systematically document the process of abstracting tasks from user requirements and domain analysis for your visualization project.

## Project Information

### Project: Real time system to detect hazardous weather conditions for Driving in the state of Illinois
### Domain: Transportation
### Date Started: [09/26/2025]
### Last Updated: [09/2/2025]
### Team Members: [Kirill Makienko - Computer Expert]

## Task Abstraction Framework

### Domain Problem Characterization
**What:** Driving in hazardous weather could lead to accidents on the road and have a great impact on traffic on a given route.

**Who:** This system will impact on commuters and travelers who use a GPS to plan their route, logistic experts (dispatchers, fleet managers and drivers) and emergency services who could be adviced on bad weather generating unique conditions or heavy traffic on their way to where they were dispatched.
[Description of target users - their roles, expertise, typical work context]

**Why:** to be able to identify how extreme weather patterns will affect a given road and suggesting safer alternative routes can reduce disruptions in transportation and significantly improve driver safety.

**Where:** This algorithm should be implemented on popular commercial GPS solutions, so users are able to plan their route not only taking traffic into accout but any wheather that could be problematic for driving.  
[Context of use - where and when this tool would be used]

**When:** This project is to be developed in the 2025 Fall semester ending on the 25th of December
[Temporal context - frequency of use, time constraints, deadlines]

**How (Currently):** Current tools include individual apps who can show future weather events on a given road but dont make it clear enough to the user how dangerous any given conditions may be.
[Current methods and tools users employ to address this problem]

## Data Characterization

### Dataset Types:
- [ ] **Tabular Data** - [Description if applicable]
- [ ] **Network Data** - [Description if applicable]  
- [ ] **Spatial Data** - [Description if applicable]
- [ ] **Temporal Data** - [Description if applicable]
- [ ] **Hierarchical Data** - [Description if applicable]
- [ ] **Other:** [Specify type and description]

### Data Attributes:

| Attribute Name | Type | Description | Importance |
|----------------|------|-------------|------------|
| [attribute1] | [Quantitative/Ordinal/Categorical] | [What it represents] | [High/Medium/Low] |
| [attribute2] | [Quantitative/Ordinal/Categorical] | [What it represents] | [High/Medium/Low] |
| [attribute3] | [Quantitative/Ordinal/Categorical] | [What it represents] | [High/Medium/Low] |

### Data Relationships:
- **Relationship 1:** [Description of how data elements relate]
- **Relationship 2:** [Description of how data elements relate]

## Task Identification

### High-Level Tasks
*These are the overarching goals users want to accomplish*

#### Task 1: [Notify users about severe weather events]
- **Description:** [There is no software that notifies the user about how dangerous it is to traverse a partch affected by a severe weather event]
- **Current Method:** [Users can use an app to obtain approximante weather data for their route, yet they dont have a reference for how dangerous it is]
- **Pain Points:** [If the data and recommendations arent easly understandable the user wont bother to use them]
- **Success Criteria:** [Users will know they were notified if they clearly understand the risk with taking any given route]
- **Frequency:** [The users will perform this task each time they plan a route]
- **Priority:** [High]

#### Task 2: [No threshold for "Severe weather"]
- **Description:** [There is no set of numbers to determine which conditions are considered dangerous for driving]
- **Current Method:** [There could be estimations done by individuals but there is no standard for this kind of information for driving]
- **Pain Points:** [There should be research done into how different weather artifacts impact driving]
- **Success Criteria:** [Determine a base number under which driving feels safe]
- **Frequency:** [The users will perform this task each time they plan a route]
- **Priority:** [High]

#### Task 3: [Identify the most computationally expensive calculations in the algorithm and minimize them]
- **Description:** [Having an algorithm that calculates which weather is going to happen at a given time on a route is a complex task, how could we simplify it to make as few calculations as possible]
- **Current Method:** [There is no current method]
- **Pain Points:** [The calculations will be made server side, many users should be able to use this program without it being an extreme load on the server]
- **Success Criteria:** [The app manages to handle multiple people making different requests at the same time]
- **Frequency:** [The users will perform this task each time they plan a route]
- **Priority:** [High]

### Mid-Level Tasks
*Breaking down high-level tasks into more specific actions*

#### For Task 1: [Notify users about severe weather events]
1. **Subtask 1.1:** [Design the UI for easy understanding]
   - **Input:** [When the page loads, the user can intuitively guess how the app works]
   - **Output:** [The user understands how to use the app without any guides]
   - **Challenges:** [Its could be complex to boil down weather data into a simple UI]

2. **Subtask 1.2:** [Show differences between different routes]
   - **Input:** [The user inputs his origin and destination]
   - **Output:** [Show multiple routes and how they compare to the fastest route and show how they avoid potentially dangerous weather paths]
   - **Challenges:** [How to make this impactfull enough for the user to care]

3. **Subtask 1.3:** [Inform the user about the risk of a route]
   - **Input:** [The user inputs his origin and destination]
   - **Output:** [The program shows a patch to avoid and shows an alternate route]
   - **Challenges:** [To make the user understand how serious the weather is and taking it could risk an accident]

#### For Task 2: [No threshold for "Severe weather"]

1. **Subtask 2.1:** [Deciding what is considered "Dangerous"]
   - **Input:** [Determine a threshold for every climate category]
   - **Output:** [Have a single number over which its prefered to avoid a route]
   - **Challenges:** [It may be impossible to come up with a single value number that determines if its better to reroute]

2. **Subtask 2.2:** [Conduct a literary review on current data conditions which impact driving]
   - **Input:** [Conduct a research on conditions under which accidents happen to try to determine dangerous thresholds]
   - **Output:** [Have a set of numbers which can serve as a guide for people to make the desicion to avoid a particular route because of wheather conditions]
   - **Challenges:** [Making a review takes into account the drivers skills and other conditions is going to make a review more difficult]

#### For Task 3: [Identify the most computationally expensive calculations in the algorithm and minimize them]

1. **Subtask 3.1:** [Determine how an algorithm of this sort works]
   - **Input:** [Given the problem, develop an algorithm that can show any weather events that crosses a route at the time a car passes trough that stretch]
   - **Output:** [Be able to know the weather conditions for a user's route]
   - **Challenges:** [This algorithm, due to the complexity of the problem, most probably is heavy on calculations and could take a long time to calculate one route]

2. **Subtask 3.2:** [Simplify the developed algorithm]
   - **Input:** [An algorithm that can show any weather events that crosses a route at the time a car passes trough that stretch]
   - **Output:** [A simplified version of that algorithm that makes less calculations and is faster to process one route]
   - **Challenges:** [How are we sure that the algorithm hasn't lost any of its efficency?]



### Low-Level Tasks
*Detailed interaction-level tasks using established taxonomies*

#### Visual Analysis Tasks (Based on Amar & Stasko, 2004):
- [ ] **Retrieve Value:** Find specific data values
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Filter:** Focus on data meeting certain criteria
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Compute Derived Value:** Calculate aggregations or transformations
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Find Extremum:** Identify minimum or maximum values
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Sort:** Order data by specific attributes
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Determine Range:** Find span of values
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Characterize Distribution:** Understand data patterns
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Find Anomalies:** Detect outliers or exceptions
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Cluster:** Group similar data points
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

- [ ] **Correlate:** Identify relationships between variables
  - *Context:* [When users need this in your domain]
  - *Example:* [Specific example from your domain]

## Task Validation

### Validation Methods Used:
- [ ] **Follow-up user interviews** - [Date(s) conducted]
- [ ] **Expert review** - [Expert consulted and date]
- [ ] **Literature validation** - [Relevant papers consulted]
- [ ] **Observation studies** - [Context and date]
- [ ] **Task walk-through** - [With whom and when]

### Validation Results:

| Task | Validated | Notes | Revisions Needed |
|------|-----------|-------|------------------|
| [Task 1] | ✓ Yes / ⚠ Partially / ✗ No | [Feedback received] | [Changes to make] |
| [Task 2] | ✓ Yes / ⚠ Partially / ✗ No | [Feedback received] | [Changes to make] |
| [Task 3] | ✓ Yes / ⚠ Partially / ✗ No | [Feedback received] | [Changes to make] |

### Key Insights:
- **Insight 1:** [What you learned about user needs]
- **Insight 2:** [What you learned about task priorities]
- **Insight 3:** [What you learned about task relationships]

## Task Prioritization

#### Essential (Must Have):
1. **Task:** [Why this is essential]
2. **Task:** [Why this is essential]

#### Important (Should Have):
1. **Task:** [Why this is important]
2. **Task:** [Why this is important]

#### Desirable (Could Have):
1. **Task:** [Why this would be valuable]
2. **Task:** [Why this would be valuable]

#### Out of Scope (Won't Have):
1. **Task:** [Why this is deferred]
2. **Task:** [Why this is deferred]

## Design Implications

### Visualization Requirements:
Based on the task analysis, the visualization needs:
- **Requirement 1:** [Specific visual encoding or feature needed]
- **Requirement 2:** [Specific visual encoding or feature needed]
- **Requirement 3:** [Specific visual encoding or feature needed]

### Interaction Requirements:
Based on the task analysis, the interface needs:
- **Interaction 1:** [Specific interaction capability needed]
- **Interaction 2:** [Specific interaction capability needed]
- **Interaction 3:** [Specific interaction capability needed]

### Information Architecture:
Based on the task analysis, the information should be organized:
- **Organization principle 1:** [How to structure information]
- **Organization principle 2:** [How to structure information]

## Task Relationships and Dependencies

### Sequential Task Flows:
1. [Task A] → [Task B] → [Task C]
   - **Rationale:** [Why these tasks happen in sequence]
   - **Design Implication:** [How interface should support this flow]

2. [Task D] → [Task E]
   - **Rationale:** [Why these tasks happen in sequence]
   - **Design Implication:** [How interface should support this flow]

### Parallel Tasks:
- [Task F] || [Task G] (can be done simultaneously)
  - **Design Implication:** [How to support parallel execution]

### Alternative Paths:
- [Task H] OR [Task I] (different approaches to same goal)
  - **Design Implication:** [How to accommodate different approaches]

## Iteration Log

### Iteration 1: [Date]
**Trigger:** [What prompted this revision - new user feedback, expert input, etc.]

**Changes Made:**
- **Change 1:** [Description of task revision]
- **Change 2:** [Description of task revision]

**Rationale:** [Why these changes were needed]

**Impact:** [How this affected other tasks or design decisions]

### Iteration 2: [Date]
**Trigger:** [What prompted this revision]

**Changes Made:**
- **Change 1:** [Description of task revision]
- **Change 2:** [Description of task revision]

**Rationale:** [Why these changes were needed]

**Impact:** [How this affected other tasks or design decisions]

## Domain-Specific Considerations

### [Your Domain] Specific Patterns:
- **Pattern 1:** [Common task pattern in your domain]
- **Pattern 2:** [Common task pattern in your domain]

### Domain Constraints:
- **Constraint 1:** [Limitation that affects task performance]
- **Constraint 2:** [Limitation that affects task performance]

### Domain Opportunities:
- **Opportunity 1:** [Unique advantage for visualization in this domain]
- **Opportunity 2:** [Unique advantage for visualization in this domain]

## Validation Against Literature

### Similar Studies Reviewed:

| Study | Domain | Similar Tasks | Key Differences | Insights Applied |
|-------|--------|---------------|-----------------|------------------|
| [Study 1] | [Domain] | [Tasks in common] | [How your context differs] | [What you learned] |
| [Study 2] | [Domain] | [Tasks in common] | [How your context differs] | [What you learned] |

### Task Taxonomy Alignment:
- **Brehmer & Munzner (2013):** [How your tasks map to their taxonomy]
- **Amar & Stasko (2004):** [How your tasks map to low-level analysis tasks]
- **Domain-specific taxonomies:** [Any field-specific task classifications]

## Next Steps

### Immediate Actions:
- [ ] [Action 1 - e.g., validate remaining tasks with users]
- [ ] [Action 2 - e.g., begin sketching designs for priority tasks]
- [ ] [Action 3 - e.g., document task-to-design mapping]

### Questions for Design Phase:
1. [Question about how to visually support specific tasks]
2. [Question about interaction design for task flows]
3. [Question about information prioritization]

### Handoff to Design:
- [ ] Task analysis complete and validated
- [ ] Priority tasks clearly identified
- [ ] Design implications documented
- [ ] Design team briefed on findings

---

## References
- Amar, R., & Stasko, J. (2004). A knowledge task-based framework for design and evaluation of information visualizations.
- Brehmer, M., & Munzner, T. (2013). A multi-level typology of abstract visualization tasks.
- [Add other relevant references for your domain]

---

*Customize this template by removing sections that aren't relevant to your project and adding domain-specific considerations as needed.*
