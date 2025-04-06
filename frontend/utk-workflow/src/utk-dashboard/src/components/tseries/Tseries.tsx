import { VegaLite } from 'react-vega'
import { VisualizationSpec } from 'vega-embed'

export default function Tseries({data, time }:{data:object, time:number}) {

  const tseries: VisualizationSpec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "description": "Stock prices of 5 Tech Companies over Time.",
    "data": {"values": data},
    // "data": {"url": "https://raw.githubusercontent.com/vega/vega/main/docs/data/stocks.csv"},
    "width": 600,
    "height": 80,
    "layer": [
      { "mark": { "type": "line" },
        "encoding": {
          "x": {"field": "t", "type": "quantitative", "axis": {"ticks": false, "labels": false, "grid": false, "title": ""}},
          "y": {"field": "v", "type": "quantitative", "axis": {"ticks": false, "labels": false, "grid": false, "title": ""}},
          "strokeDash": {"field": "c", "type": "nominal", "title": ""},
          "color": {
            "field": "c", "type": "nominal", "legend": null,
            "scale": {
              // "domain": fields.category,
              "domain": ["WRFout", "Obs"],
              // "range":  range,
            }
          }
        }
      },

      // {
      //   "mark": "rule",
      //   "encoding": {
      //     "x": {"datum": 10},
      //     "size": {"value": 2},
      //     "color": {"value": "rgb(0, 179, 179)"}
      //   }
      // }
    ]

    
  }

  return(
    <>
    <div>
      <VegaLite
        spec={tseries}
        actions={false}
        renderer={'svg'}
      />
    </div>
    </>
  )
}