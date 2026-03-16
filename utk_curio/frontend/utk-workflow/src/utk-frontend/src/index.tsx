import React from 'react';
import ReactDOM from 'react-dom';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
// bootstrap css
import 'bootstrap/dist/css/bootstrap.min.css';
import Jupyter from './Jupyter';

declare global{
  interface Window {
    JupyterReact: any;
  }
}

const entry = process.env.REACT_APP_ENTRY || 'app';
const rootEl = document.getElementById('root') as HTMLElement | null;

if (entry === 'app' && rootEl) {
  // Standard web entry: render App (this triggers the data-load logs in App.tsx)
  ReactDOM.render(<App />, rootEl);
  console.log('[Curio] Bootstrapped App entry (REACT_APP_ENTRY=app)');
} else {
  // Jupyter entry: expose JupyterReact.init so notebook can mount the component
  window.JupyterReact = {
    init: (selector: string, myData: { bar: any; scatter: any; heat: any; city: any }) => {
      selector = selector.substring(1);
      const renderComponent = (<Jupyter {...myData} />)

      ReactDOM.render(renderComponent, document.getElementById(selector));
    }
  }
  console.log('[Curio] Bootstrapped Jupyter entry (REACT_APP_ENTRY=jupyter)');
}

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
