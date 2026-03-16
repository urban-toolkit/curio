import React, {useEffect} from 'react';

// css file
import './App.css';

import {Environment, DataLoader, GrammarInterpreter} from 'utk';
import 'utk/style.css'

import $ from 'jquery';

// const pythonServerParams = require('./pythonServerConfig.json');

// ======================================================================================

// TODO: get rid of this initializer
let initializer: any;

class Initializer {
  _map: any;
  _grammarInterpreter: any;
  _mainDiv: any;

  constructor(mainDiv: any) {

    this._mainDiv = document.querySelector(mainDiv);
  }

  run(data:any) {

    this._grammarInterpreter = new GrammarInterpreter("mainInterpreter", data, this._mainDiv)

    // cave connection
    // initializeConnection(this._map); // TODO: enable CAVE connection
  }

  get map(){
    return this._map;
  }

}

export const createAndRunMap = () => {
  $('#mainDiv').empty();

  initializer = new Initializer('#mainDiv');
      
  const port = 3000; // TODO: enable vr mode

  // if(MapConfig.frontEndMode == 'vr'){
  //   port = '3001';
  // }else{
  //   port = '3000';
  // }

  // Serves data files to the map
  // Environment.setEnvironment({backend: process.env.REACT_APP_BACKEND_SERVICE_URL as string});
  // const backendUrl = process.env.REACT_APP_BACKEND_SERVICE_URL || 'http://localhost:5002';
  // Environment.setEnvironment({backend: backendUrl as string});
  //
  // const url = `${Environment.backend}/getGrammar`;
  // const started = performance.now();
  // console.log('[Curio] Data load: requesting grammar from', url);
  // DataLoader.getJsonData(url)
  //   .then(data => {
  //     const durationMs = Math.round(performance.now() - started);
  //     console.log('[Curio] Data load: received grammar payload in', durationMs, 'ms', data);
  //     initializer.run(data);
  //   })
  //   .catch(err => {
  //     const durationMs = Math.round(performance.now() - started);
  //     console.error('[Curio] Data load: failed to load grammar from backend after', durationMs, 'ms', err);
  //   });
  Environment.setEnvironment({backend: `http://localhost:5001` as string});
  const url = `${Environment.backend}/getGrammar`;
  DataLoader.getJsonData(url).then(data => {
    initializer.run(data);
  });
}

export const emptyMainDiv = () => {
  $('#mainDiv').empty();
}
 
// ======================================================================================

function App() {

  // Run only once
  useEffect(() => {
    createAndRunMap();
  }, []);

  return (
    <React.Fragment>
      <div id='mainDiv' style={{height: "100vh", width: "100%"}}>
      </div>
    </React.Fragment>
  );
}

export default App;

