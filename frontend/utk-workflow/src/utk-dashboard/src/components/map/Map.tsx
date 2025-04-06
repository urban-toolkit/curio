import { useEffect } from 'react';
import {Environment, DataLoader, GrammarInterpreter, InteractionChannel} from 'utk';
import $ from 'jquery';
import { IMasterGrammar } from 'utk';

interface MapProps {
  time: number,
  setTime: (time: number) => void
}

const Map = ({ time, setTime } : MapProps) => {
  
  // Run only once
  useEffect(() => {
    const createAndRunMap = async () => {
      $('#spatial-div').empty();
      
      // Serves data files to the map
      Environment.setEnvironment({backend: Environment.backend});
      
      const url = `${Environment.backend}/getGrammar`;
      const grammar = await DataLoader.getJsonData(url) as IMasterGrammar;

      if(grammar.variables != undefined){
        const currentTime = parseInt(grammar.variables[0].value);
        if(currentTime>0 && currentTime<11) setTime(currentTime);
      }
      
      const mainDiv = document.querySelector('#spatial-div') as HTMLElement;

      const setTimeFunction = setTime;
      InteractionChannel.addToPassedVariables("timestamp", setTimeFunction)

      const grammarInterpreter = new GrammarInterpreter("mainInterpreter", grammar, mainDiv);
    }
    createAndRunMap();

  }, []);

  useEffect(() => {
    InteractionChannel.sendData({name: "timestep", value: ""+time})
  }, [time]);

  // return <div id='spatial-div' style={{height: "100vh", width: "100%"}}></div>
  return <div id='spatial-div' style={{ height: "100vh",width: "100%"}}></div>
}

export { Map }