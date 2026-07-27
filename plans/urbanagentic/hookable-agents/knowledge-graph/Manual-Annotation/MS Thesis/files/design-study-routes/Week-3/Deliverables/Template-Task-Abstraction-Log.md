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

**Why:** to be able to identify how extreme weather patterns will affect a given road and suggesting safer alternative routes can reduce disruptions in transportation and significantly improve driver safety.

**Where:** This algorithm should be implemented on popular commercial GPS solutions, so users are able to plan their route not only taking traffic into accout but any wheather that could be problematic for driving.  

**When:** This project is to be developed in the 2025 Fall semester ending on the 25th of December

**How (Currently):** Current tools include individual apps who can show future weather events on a given road but dont make it clear enough to the user how dangerous any given conditions may be.

## Data Characterization

### Dataset Types:
- [x] **Tabular Data** - Dataframe style data
- [x] **Temporal Data** - Multiple dataframes representing data each hour

### Data Attributes:

| Attribute Name | Type | Description | Importance |
| :--- | :--- | :--- | :--- |
| **Daily Total Precipitation** | Quantitative | The total amount of precipitation (e.g., rain, snow) in millimeters (mm) over a 24-hour period. | **High** |
| **Wind Speed at 10M** | Quantitative | The speed of the wind in meters per second (m/s) at a height of 10 meters. | **High** |
| **Temperature at 2M** | Quantitative | The air temperature in Kelvin (K°) at a height of 2 meters. | **High** |
| **Heat Index** | Quantitative | A "feels like" temperature in Fahrenheit (F°) that combines air temperature and relative humidity. | Medium |
| **Relative Humidity at 2M** | Quantitative | The amount of water vapor in the air, as a percentage (%), at a height of 2 meters. | Medium |
| **Wind Direction at 10M** | Quantitative | The direction from which the wind is blowing, measured in degrees (°), at a height of 10 meters. | Medium |

### Data Relationships:

-   **Relationship 1 (Freezing Conditions):** The most critical relationship for creating hazardous winter conditions. When **Temperature at 2M** is at or below freezing (273.15 K), **Daily Total Precipitation** manifests as snow, sleet, or freezing rain. Furthermore, the combination of near-freezing **Temperature at 2M** and high **Relative Humidity at 2M** can lead to the formation of black ice or dense fog, even without active precipitation.

-   **Relationship 2 (Wind Hazard):** The danger from wind is a function of both its speed and direction. **Wind Speed at 10M** determines the force, while **Wind Direction at 10M** determines how that force is applied to a vehicle. A strong wind perpendicular to a vehicle's path (a crosswind) is a significant hazard, especially for high-profile vehicles, and is far more dangerous than a headwind or tailwind of the same speed.

-   **Relationship 3 (Reduced Visibility):** Visibility is directly impacted by the interplay of several attributes. Heavy **Daily Total Precipitation** (as rain or snow) significantly reduces visibility. This effect is compounded by high **Wind Speed at 10M**, which can create blinding, wind-driven rain or blizzard/white-out conditions with snow.

-   **Relationship 4 (Heat Index Derivation):** The **Heat Index** is a derived value that explicitly describes the relationship between **Temperature at 2M** and **Relative Humidity at 2M**. While less of a direct driving hazard, it is an important indicator of conditions that can lead to driver fatigue or vehicle stress.

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

- [x] **Compute Derived Value:** Calculate aggregations or transformations
  - *Context:* When a user is presented with a route, they need a quick, at-a-glance understanding of its overall safety without having to analyze multiple raw weather variables.
  - *Example:* The system takes multiple weather inputs (e.g., wind speed, precipitation rate, temperature) for a specific route segment and computes a single, unified "Risk Coeficient", which is then used to color-code that part of the route.

#### For Subtask 1.2: [Show differences between different routes]

- [x] **Find Extremum:** Identify minimum or maximum values
  - *Context:* After a user enters a destination, the system presents multiple route options. The user needs to quickly identify the best choice based on their priorities (e.g., safety).
  - *Example:* From a list of multiple potential routes, the system calculates shows the top wind speed for each and visually highlights the route with the lowest score, labeling it as the "Safest Route."

#### For Subtask 1.3: [Inform the user about the risk of a route]

- [x] **Find Anomalies:** Detect outliers or exceptions
  - *Context:* When a user is reviewing a specific route, they need to be explicitly alerted to any unusually dangerous segments that justify taking an alternate route.
  - *Example:* The system scans the "Risk Coeficient" for every mile of the user's chosen route and flags any segment that exceeds a critical danger threshold as an anomaly, presenting a specific pop-up alert.

#### For Subtask 2.1: [Deciding what is considered "Dangerous"]

- [x] **Characterize Distribution:** Understand data patterns
  - *Context:* Ask domain experts at DPI what is considered dangerous for driving

#### For Subtask 3.2: [Simplify the developed algorithm]

- [x] **Compute:** Identify number of calculations and algorithm complexity
  - *Context:* identify how many operations are made by the algorithm

#### For Subtask 3.2: [Simplify the developed algorithm]

- [x] **Filter:** Focus on data meeting certain criteria
  - *Context:* To optimize the algorithm for speed and reduce server load, the system needs to ignore data that is not relevant to the immediate task, reducing the total number of calculations required.

### Key Insights:
- **Insight 1:** Learned that DPI dosent have a weather predicting model
- **Insight 2:** Learned that algorithm will be more complex than initially thought

## Task Prioritization

#### Essential (Must Have):
1.  **Task 2.1: Deciding what is considered "Dangerous"**
    *   **Why this is essential:** This is the foundation of the entire project. Without expert-defined thresholds for what constitutes hazardous weather, the system cannot perform its core function of risk assessment. All other features depend on this being defined first.

2.  **Task 3.1: Determine how an algorithm of this sort works**
    *   **Why this is essential:** This is the core technical engine of the application. A functional, even if unoptimized, algorithm that can correlate a user's route with future weather events is the minimum requirement to solve the problem statement.

3.  **Task 1.3: Inform the user about the risk of a route**
    *   **Why this is essential:** This task delivers the primary value to the user. The system must be able to visually flag a dangerous segment and present a safer alternative. This directly addresses the user's need and the project's main goal.

#### Important (Should Have):
1.  **Task 1.1: Design the UI for easy understanding**
    *   **Why this is important:** An essential feature is useless if the user cannot understand it. A clear, intuitive UI is critical for user adoption and for ensuring the safety warnings are effective and not just ignored. This makes the core functionality usable.

2.  **Task 3.2: Simplify the developed algorithm**
    *   **Why this is important:** For the application to be practical and scalable, it must be fast and responsive. A slow algorithm will lead to a poor user experience and will not be able to handle multiple users. Optimization is crucial for a real-world product.

3.  **Task 1.2: Show differences between different routes**
    *   **Why this is important:** To persuade a user to take a longer but safer route, they must be able to easily compare the options. Showing the trade-offs (e.g., "+10 minutes, but avoids high-wind zone") is key to enabling an informed decision and encouraging safer behavior.

#### Desirable (Could Have):
1.  **Task: User-Customizable Thresholds**
    *   **Why this would be valuable:** Allowing advanced users (like truckers with high-profile vehicles) to set their own risk sensitivity would add significant value. However, the system must first function perfectly with universal, expert-defined thresholds.

2.  **Task: Post-Trip Analysis and Feedback**
    *   **Why this would be valuable:** Showing a user a summary after their trip ("You successfully avoided a storm that caused a 2-hour traffic jam") would be a powerful tool for building long-term trust and reinforcing the value of the system's recommendations.

#### Out of Scope (Won't Have):
1.  **Task: Full Turn-by-Turn Navigation**
    *   **Why this is deferred:** The project's goal is to be a specialized *route-planning and risk-assessment tool*, not a full-fledged replacement for Google Maps or Waze. Building a complete navigation system is a massive undertaking that distracts from the core mission.

2.  **Task: Historical Weather Data Browser**
    *   **Why this is deferred:** While the system *uses* historical data to build its models, providing an interface for users to browse past weather events is not aligned with the primary task of planning a future route. This is an analytical feature, not a planning one.

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
1. [Task 2.1] → [Task 3.1] → [Task 3.2] -> [Task 1.2]
   - **Rationale:** [The algorithm is the base of the project, defining how it works is the most important objective of the project]
   - **Design Implication:** The visualization can be implemented at a later stage, we cannot build the visualization without the data for it

2. [Task 1.1] → [Task 1.3]
   - **Rationale:** [After developing the algorithm, we can start on the visualization]
   - **Design Implication:** [How interface should support this flow]

## Iteration Log

### Iteration 1: [25-09-25]
**Trigger:** [Started the creation of the task abstraction log]

### Iteration 2: [29-09-25]
**Trigger:** [Incremental revision]

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
