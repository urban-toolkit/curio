import { VegaLite } from 'react-vega'
import { VisualizationSpec } from 'vega-embed'

export default function TseriesFocusCtx({data}:{data:object}) {
    const ctxNfocus: VisualizationSpec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "data": {"values": data},
      // "data": {"url": "https://raw.githubusercontent.com/vega/vega/main/docs/data/stocks.csv"},
      "vconcat": [{
        "width": 650,
        "mark": "line",
        "encoding": {
          "x": {"field": "t", "type": "quantitative", "scale": {"domain": {"param": "brush"}}, "axis": {"ticks": true, "labels": true, "grid": true, "title": "date"}},
          "y": {"field": "v", "type": "quantitative", "axis": {"ticks": true, "labels": true, "grid": true, "title": "value"}},
          "strokeDash": {"field": "c", "type": "nominal", "title": ""},
          "color": {
            "field": "c", "type": "nominal", "legend": null,
            "scale": {
              "domain": ["WRFout", "Obs"],
              // "range":  range,
            }
            }
        }
      }, {
        "width": 650,
        "height": 60,
        "mark": "line",
        "params": [{
          "name": "brush",
          "select": {"type": "interval", "encodings": ["x"]}
        }],
        "encoding": {
          "x": {"field": "t", "type": "quantitative", "axis": {"ticks": false, "labels": false, "grid": false, "title": "date"}},
          "y": {"field": "v", "type": "quantitative", "axis": {"ticks": false, "labels": false, "grid": false, "title": "value"}},
          "strokeDash": {"field": "c", "type": "nominal", "title": ""},
          "color": {
            "field": "c", "type": "nominal", "legend": null,
            "scale": {
              "domain": ["WRFout", "Obs"],
              // "range":  range,
            }
          }
        }
      }]
    } 
  
    return(
      <>
      <div>
        <VegaLite
          spec={ctxNfocus}
          actions={false}
          renderer={'svg'}
        />
      </div>
      </>
    )
  
  }

// export default function TseriesFocusCtx({data}:{data:object}) {
//     const ctxNfocus: VisualizationSpec = {
//       "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
//       // "data": {"values": data},//{"url": "https://raw.githubusercontent.com/vega/vega/main/docs/data/sp500.csv"},
//       "data": {"url": "https://raw.githubusercontent.com/vega/vega/main/docs/data/sp500.csv"},
//       "vconcat": [{
//         "width": 650,
//         "mark": "line",
//         "encoding": {
//           "x": {
//             "field": "date",
//             "type": "temporal",
//             "scale": {"domain": {"param": "brush"}},
//             "axis": {"title": ""}
//           },
//           "y": {"field": "price", "type": "quantitative"}
//         }
//       }, {
//         "width": 650,
//         "height": 60,
//         "mark": "line",
//         "params": [{
//           "name": "brush",
//           "select": {"type": "interval", "encodings": ["x"]}
//         }],
//         "encoding": {
//           "x": {
//             "field": "date",
//             "type": "temporal"
//           },
//           "y": {
//             "field": "price",
//             "type": "quantitative",
//             "axis": {"tickCount": 3, "grid": false}
//           }
//         }
//       }]
//     } 
  
//     return(
//       <>
//       <div>
//         <VegaLite
//           spec={ctxNfocus}
//           actions={false}
//           renderer={'svg'}
//         />
//       </div>
//       </>
//     )
  
//   }