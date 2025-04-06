import React, {useEffect} from 'react';

// css file
import './Map.css';

import {Environment, DataLoader, GrammarInterpreter} from 'utk';
import $ from 'jquery';

let initializer: any;

class Initializer {
  _map: any;
  _grammarInterpreter: any;
  _mainDiv: any;

  constructor(mainDiv: any) {

    this._mainDiv = document.querySelector(mainDiv);

    
  }

  run(data:any) {
    this._grammarInterpreter = new GrammarInterpreter("mainInterpreter", data, this._mainDiv);
  }

}

export const createAndRunMap = () => {
  $('#spatial-div').empty();

  initializer = new Initializer('#spatial-div');
        
  // Serves data files to the map
  // Environment.setEnvironment({backend: process.env.REACT_APP_BACKEND_SERVICE_URL as string});
  Environment.setEnvironment({backend: `http://localhost:5001` as string});
  const url = `${Environment.backend}/getGrammar`;
  DataLoader.getJsonData(url).then(data => {
    initializer.run(data);
  });
}

export const emptyMainDiv = () => {
  $('#spatial-div').empty();
}

function Map() {
  // Run only once
useEffect(() => {
  createAndRunMap();
}, []);

  return <div id='spatial-div' style={{height: "100vh", width: "100%"}}></div>
}

export { Map }