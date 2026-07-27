## Project Overview

### Title: A Framework for Integrating Probabilistic Weather Forecasts into Vehicular Routing 




















### Domain: Transportation

### Problem Statement:
Driving in hazardous weather conditions can be dangerous for all drivers, regardless of skill level. With the heavy reliance on cars and public transportation for daily travel, the ability to monitor and predict severe weather events is critical. 
Identifying when storms, violent winds, or other extreme weather patterns will affect a given road and suggesting safer alternative routes can reduce disruptions in transportation and significantly improve driver safety.

Current route-finding methods typically calculate risk only at the time a query is made. However, there is a need for systems that can predict whether extreme weather conditions will affect a selected route at the actual time a driver will be traveling.

### Target Users:
- **Primary Users:** 
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


- **Secondary Users:** 

  1. Delivery user: Their delivery's success and timing are determined by the route planned for the driver (Primary User).
  * They want their packages to arrive on time and without any damage
  * They would get better Customer Service: recieve a notification about a delay caused by a weather event.

  2. Recipient from Emergency responders:
  * Emergency servies may arrive quicker on site 
  * Responders may be better equiped to attend the emergency given the predicted weather



- **Stakeholders:**
 
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

2. How can the interface distill complex weather hazards along an entire route into a simple, understandable, and quantifiable summary that can be easily compared against other routes?

3. Is it possible to generate a research framework to ease the collaborations process between computer experts and meteorologists? 

### Out of Scope:
  1. Any implementation with current systems
  3. The impact on driver safety
  4. The impact on traffic for alternate routes
  5. The impact on traffic on uninformed drivers
  6. The impact of weather on traffic in general

## Background and Context

### Domain Background:
The ability to accurately forecast weather is a cornerstone of modern logistics, public safety, and daily life. This predictive capability has a profound impact across countless sectors, from optimizing global airplane and maritime shipping routes to informing an individual's simple decision to take an umbrella. At the core of this field, meteorologists and atmospheric scientists utilize sophisticated tracking models to predict weather patterns with ever-increasing accuracy.

Extreme weather events are a direct and growing threat to driver safety. According to AerisIQ, more than 2500 deaths were recorded due to extreme weather and according to the Federal Highway administration over 3800 people are killed in weather related crashes each year. The primary challenge is providing drivers with the tools to make proactive, informed decisions to avoid these hazardous conditions, thereby preventing accidents, reducing traffic congestion, and ultimately saving lives.

### Existing Solutions:
There are multiple systems who can warn a driver about hazardous weather, yet they all have their limitations in comparison to this project.
- Weather on wheels is an app developed by the Texas A&M University at Corpus Christi which pulls data from the US National Weather Service, it has multiple limitations compared to this app, where they dont take into account any thresholds for hazardous conditions for driving and only show simple weather forecasts and temperature forcasts
- Highway weather is a commercial app powered by their own propietary technology, this app shows weather forcast by hour and shows precipitation and wind speeds, yet as Weather on wheels it dosent show weather alerts, yet there is no intuitive way for a user to know if any forecast is dangerous enough.
- "Drive weather with live radar" is paid app made by Concept Elements LLC which infroms the user about weather in a users route, they try to show as many points as they can but they provide even less information on hazardous weather events   
- Several systems such as HIWAS, METAR, SPECI and others can help pilots and air traffic controllers to decide if any rerouting is needed to avoid dangerous weather patches, the problem with these commercial airline solutions is that they rely way too much on human supervision to take any action 

### Why Visualization?:

While weather forecasting today is driven by complex computational models, the act of understanding weather remains a profoundly observational and visual exercise. It is incredibly difficult to comprehend the dynamic, multi-dimensional nature of a weather system by looking at tables of intensities, probabilities, and coordinates.

A driver cannot be expected to interpret complex weather data. An interface that can reduce complexities into an understanbale format with route alternatives reccomendations based on weather is of great importance to empower the user to make the best desicions.

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
- **Technology:** OSMNX is going to be used for implementing a path tracing algorithm to find the route between 2 points, pandas and matplotlib are going to be used to manipulate the data and visualize it in development.
## Data and Technology

### Data Sources:
- **Primary Data:** [Main dataset(s) to be visualized]
  - Source: Data comes from the DPI
  - Format: the format for all data is in .nc files, where Daily total Precipitation in mm, Heat Index in Fahrenheit, Relative Humidity at 2 meters, Temperature at 2 Meters in Kelvin, Wind Direction Speed direction at 10 Meters in degrees and Wind Speed Wind speed at 10 Meters in m/s is presented for 3 months for the whole state of Illinois, in a resolution of 1km in 1 hour snapshots weighing around 103 GB in total  
  - Access: The data will be obtained by pulling it off the AerisIQ server and saving it into a portable SSD to be transported
  - Quality: A big limitation of the data is that it only provides a data point each hour, meaning that its difficult to use this data out of the box for any commuter routes predictions

### Technology Stack:
- **Development:** A Python backend (like FastAPI) will be used to be able to use Pandas to manupulate the data, React + Vue.js will be used for the frontend part of the application and if any database is needed, MongoDB will be used for its GeoSpatial capabilities
- **Visualization:** Map box will be used for the map, calculating routes and imposing weather data on routes.
- **Data Processing:** Pandas and Geopandas will be used for the data cleaning and modelling process.

### Technical Constraints:
  1. This project wont integrate with any existing applications, yet it will be developed with the intention of any person being able to take the weather simulation algorithm and easly apply it to any other project


### Contingency Plans:
- **If data access is delayed:** Data is not the only part of the project that requires attention, documentation, project proposals and web development may take even more time to be developed in comparison to data modelling 
- **If technical implementation is more complex than expected:** Either: To reduce the scope of the project to make it achievable in the remaining time or seek out to programmers who have worked on a similar implementation before for their help. 

## Expected Outcomes

### Immediate Deliverables:
- A map which allows the user to input an origin and destination and shows if any hazardous weather events will happen, then to show safe alternative routes 

### Potential Impact:
- **For Users:** Users can check weather conditions and assess risks from adverse weather on their planned route.
- **For Domain:** Will allow to start compiling data about user desicions on hazardous weather and traffic patterns in tough weather conditions
- **For Research:** With this project, we develop a way of communicating probabilistic events to non expert users and we develop a way of communicating Computer Science concepts to experts outside the visualization domain.

### Future Work:
- Find a dataset that would allow researchers to determine the impact of weather events on traffic and be able to predict how much a route would be delayed for any given weather event.
- Implement the algorithm results into google maps or Mapbox for ease of use

## Evaluation Plan

### Success Criteria:
- **Usability:** By having a metric of how many people visit the website and calculating a median of how many people visit the site each week or month
- **Utility:** To asses utility we could log the task completion rate, for example if the user only wirtes its origin and not destination we know the user didnt finished the task, another way we could asses utility is to have a quick 5 star rating asking the user "Was this map helpful for your trip?"
- **Adoption:** Are people actually using it? To measure this without leaving any type of cookie we could have server side metrics like how many times routes were calculated

### Evaluation Methods:
- User Testing: For user testing we could perform a simple traditional usability testing or could test with the "Think-Aloud" methodology
## Communication and Dissemination

### Stakeholder Updates:
- **Frequency:** Big progress will be presented once a week, smaller consultations may happen more often
- **Format:** Weekly progress reports will be done via Zoom and smaller consultations may be done via Email or Slack
- **Audience:** Dr. Fabio Miranda, Dr. Ashish Sharma, Dr. Abhinav Wadhwa, Kazi Shahrukh, Vamsi Dath, Kirill Makienko

### Sharing Results:
- **Internal:** To be determined on a case by case basis
- **External:** [Conference presentations, publications, open source]
- **Community:** [How insights will benefit the broader community]

## Approval and Sign-off

### Stakeholder Approval:
- [ ] [Dr. Ashish Sharma - Domain expert] - Date: ______
- [ ] [Dr. Abhinav Wadhwa - Domain expert] - Date: ______
- [ ] [Kirill Makienko - Computer expert] - Date: ______

---

## Appendices

### A. Related Work

https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html
https://www.faa.gov/sites/faa.gov/files/15_phak_ch13.pdf
https://bravo6flightacademy.com/mastering-the-skies-the-role-of-weather-in-pilot-training-safety/
https://ops.fhwa.dot.gov/weather/roadimpact.htm
https://aerisiq.climate-dpi.org/
