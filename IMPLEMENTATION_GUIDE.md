# Implementation Guide: Adding Three Tabs to Your Node

## Overview
This guide shows you how to implement three tabs in your node following your supervisor's guidance about using BoxEditor and components from the editing folder.

## Key Principles (Following Supervisor's Guidance)

### 1. **Receive Results from Backend**
- Modify the `useEffect` where you process `data.input` or `output.content`
- This is where you transform your backend data into tab content
- Example location: ```72:150:utk_curio/frontend/urban-workflows/src/components/DataPoolBox.tsx```

### 2. **Use Components from Editing Folder**
- **DO NOT** use inheritance
- **DO** use the `BoxEditor` component from `./editing/BoxEditor`
- **DO** create a custom `ContentComponent` that uses Bootstrap tabs
- **DO** pass your `ContentComponent` to `BoxEditor` via the `contentComponent` prop

## Implementation Steps

### Step 1: Import Required Dependencies
```typescript
import BoxEditor from "./editing/BoxEditor";
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";
```

### Step 2: Add State for Tab Management
```typescript
const [activeTab, setActiveTab] = useState<string>("0");
const [tabData, setTabData] = useState<any[]>([]);
```

### Step 3: Process Backend Data (Key Location)
```typescript
useEffect(() => {
    const processDataAsync = async () => {
        try {
            // Process your input data here
            let processedData = data.input;
            
            // Create three different views of your data
            const tab1Data = {
                title: "Summary View",
                content: processedData.summary || "No summary available",
                type: "summary"
            };
            
            const tab2Data = {
                title: "Detailed View", 
                content: processedData.details || "No details available",
                type: "details"
            };
            
            const tab3Data = {
                title: "Analysis View",
                content: processedData.analysis || "No analysis available", 
                type: "analysis"
            };

            // Set the tab data
            setTabData([tab1Data, tab2Data, tab3Data]);
            
            // Update output
            setOutput({ 
                code: "success", 
                content: JSON.stringify([tab1Data, tab2Data, tab3Data], null, 2) 
            });
            
            // Notify downstream
            data.outputCallback(data.nodeId, [tab1Data, tab2Data, tab3Data]);
            
        } catch (error) {
            console.error("Error processing data:", error);
            setTabData([]);
            setOutput({ code: "error", content: "Failed to process data." });
        }
    };

    processDataAsync();
}, [data.input, data.newPropagation]);
```

### Step 4: Create Content Component
```typescript
const ContentComponent = ({
    tabData,
    activeTab,
}: {
    tabData: any[];
    activeTab: string;
}) => {
    const renderTabContent = (data: any) => {
        switch (data.type) {
            case "summary":
                return (
                    <div style={{ padding: "15px" }}>
                        <h4>Summary</h4>
                        <p>{data.content}</p>
                    </div>
                );
                
            case "details":
                return (
                    <div style={{ padding: "15px" }}>
                        <h4>Detailed Information</h4>
                        <div style={{ 
                            backgroundColor: "#f8f9fa", 
                            padding: "10px", 
                            borderRadius: "5px",
                            fontFamily: "monospace",
                            fontSize: "12px"
                        }}>
                            {data.content}
                        </div>
                    </div>
                );
                
            case "analysis":
                return (
                    <div style={{ padding: "15px" }}>
                        <h4>Analysis Results</h4>
                        <div style={{ 
                            border: "1px solid #dee2e6", 
                            padding: "10px", 
                            borderRadius: "5px" 
                        }}>
                            {data.content}
                        </div>
                    </div>
                );
                
            default:
                return (
                    <div style={{ padding: "15px", textAlign: "center", color: "#666" }}>
                        No data available for this tab.
                    </div>
                );
        }
    };

    return (
        <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
            <Tabs
                id="three-tabs"
                activeKey={activeTab}
                onSelect={(k) => setActiveTab(k || "0")}
                className="mb-3"
                style={{ flexShrink: 0 }}
            >
                {Array.isArray(tabData) && tabData.length > 0 ? (
                    tabData.map((tab, index) => (
                        <Tab 
                            eventKey={index.toString()} 
                            title={tab.title} 
                            key={index}
                            style={{ flex: 1, overflow: "auto" }}
                        >
                            <div style={{ 
                                height: "calc(100vh - 200px)", 
                                overflowY: "auto",
                                padding: "10px"
                            }}>
                                {renderTabContent(tab)}
                            </div>
                        </Tab>
                    ))
                ) : (
                    <Tab eventKey="0" title="No Data">
                        <div style={{ 
                            padding: "20px", 
                            textAlign: "center", 
                            color: "#666",
                            height: "calc(100vh - 200px)"
                        }}>
                            No data available. Please check your input.
                        </div>
                    </Tab>
                )}
            </Tabs>
        </div>
    );
};
```

### Step 5: Use BoxEditor with Content Component
```typescript
<BoxEditor
    customWidgetsCallback={customWidgetsCallback}
    contentComponent={
        <ContentComponent
            tabData={tabData}
            activeTab={activeTab}
        />
    }
    setSendCodeCallback={(_: any) => {}}
    code={false} // Set to true if you need code editing
    grammar={false} // Set to true if you need grammar editing
    widgets={true} // Set to true if you need custom widgets
    provenance={false} // Set to true if you need provenance
    setOutputCallback={setOutput}
    data={data}
    output={output}
    boxType={BoxType.YOUR_BOX_TYPE} // Replace with your box type
    defaultValue={""}
    readOnly={false}
/>
```

## Pattern from DataPoolBox

The DataPoolBox example shows the exact pattern:

1. **Data Processing**: ```72:150:utk_curio/frontend/urban-workflows/src/components/DataPoolBox.tsx```
2. **Content Component**: ```672:890:utk_curio/frontend/urban-workflows/src/components/DataPoolBox.tsx```
3. **BoxEditor Usage**: ```850:890:utk_curio/frontend/urban-workflows/src/components/DataPoolBox.tsx```

## Key Differences for Three Fixed Tabs

Instead of dynamic tabs based on data, you create three fixed tabs:

```typescript
<Tabs
    id="data-tabs"
    activeKey={activeTab}
    onSelect={(k) => setActiveTab(k || "0")}
    className="mb-3"
>
    {/* Tab 1: Summary View */}
    <Tab eventKey="0" title="Summary">
        <div style={{ padding: "15px" }}>
            <h4>Summary View</h4>
            <p>This tab shows a summary of the data.</p>
            <ContentComponent tabData={tabData} activeTab={activeTab} />
        </div>
    </Tab>
    
    {/* Tab 2: Detailed View */}
    <Tab eventKey="1" title="Details">
        <div style={{ padding: "15px" }}>
            <h4>Detailed View</h4>
            <p>This tab shows detailed information.</p>
            <ContentComponent tabData={tabData} activeTab={activeTab} />
        </div>
    </Tab>
    
    {/* Tab 3: Analysis View */}
    <Tab eventKey="2" title="Analysis">
        <div style={{ padding: "15px" }}>
            <h4>Analysis View</h4>
            <p>This tab shows analysis results.</p>
            <ContentComponent tabData={tabData} activeTab={activeTab} />
        </div>
    </Tab>
</Tabs>
```

## Important Notes

1. **BoxEditor Integration**: The `BoxEditor` component handles the tab navigation and layout automatically
2. **Content Component**: Your custom content goes in the `contentComponent` prop
3. **State Management**: Use `activeTab` and `tabData` to manage tab state
4. **Backend Integration**: Process your data in the `useEffect` and create tab content there
5. **Reusability**: The `ContentComponent` can be reused across different tabs with different data

## Files Created

- `example_three_tabs_implementation.tsx` - Basic implementation
- `example_data_pool_style_tabs.tsx` - Following DataPoolBox pattern exactly
- `IMPLEMENTATION_GUIDE.md` - This guide

Follow this pattern to implement your three tabs while adhering to your supervisor's guidance about using BoxEditor and avoiding inheritance. 