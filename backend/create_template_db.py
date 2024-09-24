import sqlite3
from uuid import uuid4

conn = sqlite3.connect('template.db')

cursor = conn.cursor()

command = """
CREATE TABLE template (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(50) NOT NULL,
    description TEXT,
    accessLevel VARCHAR(50) NOT NULL,
    code TEXT NOT NULL,
    custom BOOLEAN NOT NULL
);
"""

cursor.execute(command)
conn.commit()

conn.close()

conn = sqlite3.connect('template.db')
cursor = conn.cursor()

template = {
    "id": str(uuid4()),  
    "type": "DATA_LOADING", 
    "name": "Parks (OSM)", 
    "description": "Load parks for Chicago using OSM", 
    "accessLevel": "ANY", 
    "code": """import utk 
uc = utk.OSM.load([!! bbox$INPUT_LIST_VALUE$[41.88043474773062,-87.62760230820301,41.89666220782541,-87.59872148227429] !!], layers=[[!! layer$SELECTION$parks$parks;water !!]]) 
gdf = uc.layers['gdf']['objects'][0] 
gdf.metadata = {'name': [!! layer$SELECTION$parks$parks;water !!]} 
return gdf""",
    "custom": 0  
}

cursor.execute("""
INSERT INTO template (id, name, type, description, accessLevel, code, custom)
VALUES (?, ?, ?, ?, ?, ?, ?)
""", (
    template["id"], 
    template["name"], 
    template["type"], 
    template["description"], 
    template["accessLevel"], 
    template["code"], 
    int(template["custom"])  
))

conn.commit()

conn.close()