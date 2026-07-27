## Project Overview

### Title: Real time system to detect hazardous weather conditions for Driving in the state of Illinois

### Domain: Transportation

### Problem Statement:
Driving in hazardous weather conditions can be dangerous for all drivers, regardless of skill level. With the heavy reliance on cars and public transportation for daily travel, the ability to monitor and predict severe weather events is critical. 
Identifying when storms, violent winds, or other extreme weather patterns will affect a given road and suggesting safer alternative routes can reduce disruptions in transportation and significantly improve driver safety.

Current route-finding methods typically calculate risk only at the time a query is made. However, there is a need for systems that can predict whether extreme weather conditions will affect a selected route at the actual time a driver will be traveling.

### Target Users:
- **Primary Users:** [Main audience - their roles, expertise level, typical tasks]
  1. Commuters and travelers. 
  * They use GPS to navigate usually small to medium distances like commutes to work, school runs, or personal trips. 
  * Their primary goal is often minimizing travel time.
  * May be willing to drive through moderate adverse weather if it doesn't significantly impact their schedule, potentially underestimating the risk.

  2. Logistics Professional. 
  * They usually plan medium to long haul trips
  * Meeting strict delivery schedules is critical, but safety and avoiding damage are paramunt.
  * A single weather-related incident can have massive financial and logistical consequences.
  * Large-scale weather systems (blizzards, hurricanes, high-wind events) that can shut down entire regions or make driving extremely hazardous.
  * The high cost of delays, fuel spent on rerouting, and potential damage to weather-sensitive cargo.
  
  3. Last-Mile Delivery
  * Usually plan in city routes
  * Ensure on-time delivery for a high volume of packages or food orders.
  * Protect cargo from weather damage
  * A single blocked road can disrupt an entire, carefully optimized delivery sequence, leading to multiple failed deliveries and increased operational costs.

  4. Emergency responder: 
  * Usually priorize being on site as quickly as possible meaning they want to avoid traffic jammed areas
  * Program may reroute if it knows about reports of blocked roads by fallen objects or accidents not related to their call 
  * Could be adviced on taking extra equipment for specific weather events 


- **Secondary Users:** [Additional users who might benefit - their relationship to primary users]

  1. Delivery user: Their delivery's success and timing are determined by the route planned for the driver (Primary User).
  * They want their packages to arrive on time and without any damage
  * They would get better Customer Service: recieve a notification about a delay caused by a weather event.

  2. Recipient from Emergency responders:
  * Emergency servies may arrive quicker on site 
  * Responders may be better equiped to attend the emergency given the predicted weather



- **Stakeholders:** [Others who care about the outcome but may not directly use the tool]
 
  1. Weataher researchers: Domain experts who study how weather pattern behave and their real world effects
  * To understand the socio-economic impact of weather on transportation.
  * To understand how different user groups react to specific weather alerts.


  2. Urban planners: Domain experts who can study the impact of weather on traffic 
  * To identify infrastructure weaknesses and build more resilient transportation networks.
  * To optimize traffic flow and public safety during adverse weather events.
  * To justify funding for infrastructure projects
  * To study how weather-related incidents create cascading traffic jams throughout the city

## Project Scope

### Goals and Objectives:
1. **Primary Goal:** Develop an interactive visualization tool that helps users identify the safest route between two points using real-time and simulated weather data.
2. **Secondary Goals:** Create an algorithm that can be implemented into existing mapping software to find and avoid extreme weather events

3. **Success Metrics:** To  have a comprehensive research framework for systematic visualization design

### Research Questions:
1. To what extent does predictive weather information influence a driver's route selection, and what are the key factors that determine their adherence to safer, alternative routes?
[Research question 1 - what you want to learn about users/domain]

2. How can the interface distill complex weather hazards along an entire route into a simple, understandable, and quantifiable summary that can be easily compared against other routes?
[Research question 2 - what you want to learn about visualization effectiveness]

3. Is it possible to generate a research framework to ease the collaborations process between computer experts and meteorologists? 
[Research question 3 - what you want to learn about design process]

### Out of Scope:
- [What you explicitly will NOT address in this project]
- [Limitations or boundaries you're setting]

  1. Any implementation with current systems
  2. Any sort of weather modelling system
  3. The impact on driver safety
  4. The impact on traffic for alternate routes
  5. The impact on traffic on uninformed drivers
  6. The impact of weather on traffic in general

## Background and Context

### Domain Background:
The ability to accurately forecast weather is a cornerstone of modern logistics, public safety, and daily life. This predictive capability has a profound impact across countless sectors, from optimizing global airplane and maritime shipping routes to informing an individual's simple decision to take an umbrella. At the core of this field, meteorologists and atmospheric scientists utilize sophisticated tracking models to predict weather patterns with ever-increasing accuracy.

Extreme weather events are a direct and growing threat to driver safety. According to AerisIQ, more than 2500 deaths were recorded due to extreme weather and according to the Federal Highway administration over 3800 people are killed in weather related crashes each year. The primary challenge is providing drivers with the tools to make proactive, informed decisions to avoid these hazardous conditions, thereby preventing accidents, reducing traffic congestion, and ultimately saving lives.

[Provide context about the application domain. What are the key concepts, challenges, and current practices?]

### Existing Solutions:
There are multiple systems who can warn a driver about hazardous weather, yet they all have their limitations in comparison to this project.
- Weather on wheels is an app developed by the Texas A&M University at Corpus Christi which pulls data from the US National Weather Service, it has multiple limitations compared to this app, where they dont take into account any thresholds for hazardous conditions for driving and only show simple weather forecasts and temperature forcasts
- Highway weather is a commercial app powered by their own propietary technology, this app shows weather forcast by hour and shows precipitation and wind speeds, yet as Weather on wheels it dosent show weather alerts, yet there is no intuitive way for a user to know if any forecast is dangerous enough.
- "Drive weather with live radar" is paid app made by Concept Elements LLC which infroms the user about weather in a users route, they try to show as many points as they can but they provide even less information on hazardous weather events   
- Several systems such as HIWAS, METAR, SPECI and others can help pilots and air traffic controllers to decide if any rerouting is needed to avoid dangerous weather patches, the problem with these commercial airline solutions is that they rely way too much on human supervision to take any action 

[Describe current tools, methods, or approaches used in this domain. What are their strengths and limitations?]

### Why Visualization?:

While weather forecasting today is driven by complex computational models, the act of understanding weather remains a profoundly observational and visual exercise. It is incredibly difficult to comprehend the dynamic, multi-dimensional nature of a weather system by looking at tables of intensities, probabilities, and coordinates.

A driver cannot be expected to interpret complex weather data. An interface that can reduce complexities into an understanbale format with route alternatives reccomendations based on weather is of great importance to empower the user to make the best desicions.


[Explain why visualization is a promising approach for this problem. What aspects of the challenge are visual in nature?]

## Project Plan

### Timeline: [Start Date] - [End Date] (Total: [X] weeks/months)

Using the "Design Study "Lite" Method" we can estimate the duration of each stage as follows:

| Stage | Duration | Key Activities | Deliverables |
|-------|----------|----------------|--------------|
| Stage 1: Abstract Phase | [2] weeks | User interviews, task analysis | Task abstraction, user requirements |
| Stage 2: Design Phase | [2] weeks | Sketching, prototyping | Design concepts, digital prototypes |
| Stage 3: Build Phase | [2] weeks | Implementation, testing | Working visualization tool |
| Stage 4: Evaluate Phase | [1] weeks | User testing, evaluation | Usability findings, design validation |
| Stage 5: Post-Study | [1] weeks | Documentation, reflection | Lessons learned, methodology insights |

### Milestones:
- **Milestone 1:** [10/03/25] - [Deliver the project proposal]
- **Milestone 2:** [10/17/25] - [Deliver the final designs]
- **Milestone 3:** [11/14/25] - [Deliver a working prototype]
- **Milestone 4:** [11/28/25] - [Deliver final program]

## Team and Resources

### Team Members:

| Name | Role | Responsibilities |
|------|------|------------------|
| Dr. Fabio Miranda | Computer Expert | Advisor professor |
| Dr. Ashish Sharma | Weather Domain Expert | Provide expert knowledge |
| Kirill Makienko | Computer Expert | Developing the visualization |

### Required Expertise:
- **Domain Expertise:** Dr. Ashish Sharma provides his experience in weather research to be able to get the right information togenerate the best and most impactful visualization possible
- **Technical Skills:** Kirill Makienko provides the knowhow on how to manupulate the data provided by Dr. Ashish to be able to extract meaningfull information from it and be able to apply it to a meaningfull visualization

### Resources Needed:
- **Data:** Data required is weather forcast data which will be provided by Dr. Ashish Sharma and Dr. Abhinav Wadhwa via the DP Institute
- **Technology:** A free tier Map Box licence will be required, a [Software, hardware, licenses, computing resources]
- **Participants:** [Number and type of users needed for research activities]
- **Budget:** No budget is required

## Data and Technology

### Data Sources:
- **Primary Data:** [Main dataset(s) to be visualized]
  - Source: [Where data comes from]
  - Format: [File type, structure, size]
  - Access: [How data will be obtained, any restrictions]
  - Quality: [Known data quality issues or limitations]

- **Secondary Data:** [Additional supporting data]
  - [Similar details as above]

### Technology Stack:
- **Development:** A Python backend (like FastAPI) will be used to be able to use Pandas to manupulate the data, React + Vue.js will be used for the frontend part of the application and if any database is needed, MongoDB will be used for its GeoSpatial capabilities
- **Visualization:** Map box will be used for the map, calculating routes and imposing weather data on routes.
- **Data Processing:** Pandas and Geopandas will be used for the data cleaning and modelling process.

### Technical Constraints:
- [Any technical limitations or requirements to consider]
- [Integration requirements with existing systems]
- [Performance or scalability requirements]

  1. This project wont integrate with any existing applications, yet it will be developed with the intention of any person being able to take the weather simulation algorithm and easly apply it to any other project
  2.  


## Risks and Mitigation

### Potential Risks:
1. **Risk:** [Description of potential problem]
   - **Likelihood:** [High/Medium/Low]
   - **Impact:** [High/Medium/Low]
   - **Mitigation:** [How you'll prevent or address this risk]

2. **Risk:** [Description of potential problem]
   - **Likelihood:** [High/Medium/Low]
   - **Impact:** [High/Medium/Low]
   - **Mitigation:** [How you'll prevent or address this risk]

### Contingency Plans:
- **If data access is delayed:** [Alternative approach]
- **If user recruitment is difficult:** [Alternative approach]
- **If technical implementation is more complex than expected:** [Alternative approach]

## Expected Outcomes

### Immediate Deliverables:
- A map which allows the user to input an origin and destination and shows if any hazardous weather events will happen, then to show safe alternative routes 
- [Research insights and findings]
- [Documentation and process learnings]

### Potential Impact:
- **For Users:** [How this will benefit the target users]
- **For Domain:** [How this will advance understanding in the domain]
- **For Research:** [How this will contribute to visualization/HCI research]

### Future Work:
- Find a dataset that would allow researchers to determine the impact of weather events on traffic and be able to predict how much a route would be delayed for any given weather event.
[Potential extensions or follow-up projects]
- [How this project might scale or evolve]

## Evaluation Plan

### Success Criteria:
- **Usability:** [How you'll measure if users can effectively use the tool]
- **Utility:** [How you'll measure if the tool provides value]
- **Adoption:** [How you'll measure if users would actually use this]

### Evaluation Methods:
- [User testing approaches]
- [Expert evaluation methods]
- [Performance or efficiency measurements]

### Validation Strategy:
- [How you'll validate design decisions]
- [How you'll validate research insights]
- [How you'll validate methodology contributions]

## Communication and Dissemination

### Stakeholder Updates:
- **Frequency:** [How often you'll provide progress updates]
- **Format:** [Meetings, reports, demos, etc.]
- **Audience:** [Who needs to be kept informed]

### Documentation:
- [What documentation will be maintained throughout]
- [How process learnings will be captured]
- [How code and designs will be documented]

### Sharing Results:
- **Internal:** [How results will be shared within organization]
- **External:** [Conference presentations, publications, open source]
- **Community:** [How insights will benefit the broader community]

## Approval and Sign-off

### Stakeholder Approval:
- [ ] [Stakeholder 1 name and title] - Date: ______
- [ ] [Stakeholder 2 name and title] - Date: ______
- [ ] [Stakeholder 3 name and title] - Date: ______

### Resource Confirmation:
- [ ] Team availability confirmed
- [ ] Data access confirmed
- [ ] Technology resources confirmed
- [ ] Budget approved (if applicable)

### Next Steps:
After approval:
1. [First action to take]
2. [Second action to take]
3. [Third action to take]

---

## Appendices

### A. Related Work

https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html
https://www.faa.gov/sites/faa.gov/files/15_phak_ch13.pdf
https://bravo6flightacademy.com/mastering-the-skies-the-role-of-weather-in-pilot-training-safety/
https://ops.fhwa.dot.gov/weather/roadimpact.htm
https://aerisiq.climate-dpi.org/



[Brief literature review or survey of related projects]

### B. Preliminary Analysis
[Any initial data exploration or user research already conducted]

### C. Technical Specifications
[Detailed technical requirements if available]

### D. Budget Breakdown
[Detailed budget if applicable]

---

*This template should be customized for your specific project and organizational context. Remove sections that aren't relevant and add domain-specific details as needed.*
